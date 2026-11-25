{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.gen9-t4-ocsd;
  placeholder = "gen9-t4-ocsd-workload.service";
  workloadUnits = if cfg.workloadUnits == [ ] then [ placeholder ] else cfg.workloadUnits;
in
{
  options.services.gen9-t4-ocsd = {
    enable = lib.mkEnableOption "the iLO 4 OCSD thermal bridge for an NVIDIA GPU in an HPE ProLiant Gen9";

    profile = lib.mkOption {
      type = lib.types.enum [
        "dl380-gen9-t4"
        "ml350-gen9-p100"
      ];
      example = "ml350-gen9-p100";
      description = ''
        Qualified platform (chassis, GPU PCI address, native OCSD layout, iLO sensor).
        The daemon refuses to start if the host's DMI product name does not match.
        See docs/platforms/ in the repository.
      '';
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The bridge package.";
    };

    nvidiaSmi = lib.mkOption {
      type = lib.types.path;
      default = "${config.hardware.nvidia.package.bin}/bin/nvidia-smi";
      defaultText = lib.literalExpression ''"''${config.hardware.nvidia.package.bin}/bin/nvidia-smi"'';
      description = "nvidia-smi used to read the GPU temperature.";
    };

    iloSensor = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "27-PCI 3";
      description = ''
        Override the profile's iLO sensor name for the published record (as shown
        by `ipmitool sdr list`). iLO registers the sensor only after an iLO reset
        while the bridge is publishing.
      '';
    };

    iloDisplayOffset = lib.mkOption {
      type = lib.types.int;
      default = 15;
      description = "Degrees iLO adds to the published value when displaying the sensor.";
    };

    publishOffset = lib.mkOption {
      type = lib.types.ints.between 0 15;
      default = 0;
      example = 10;
      description = ''
        Publish the GPU temperature this many degrees higher so iLO's fan curve
        engages earlier. The record's caution/continuous thresholds shift equally;
        the workload stop (82 C) and restore cooldown (55 C) stay on the real GPU
        temperature. Capped at 15 by the record's 100 C byte limit.
      '';
    };

    workloadUnits = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "ollama.service" ];
      description = ''
        systemd services that keep the GPU busy. The bridge stops them on a thermal
        trip (>= 82 C or telemetry loss) and before giving up its OCSD slot. Empty
        means a no-op placeholder unit (${placeholder}), for GPU work that is not
        a host service (for example Kubernetes pods).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
        message = "services.gen9-t4-ocsd only supports x86_64-linux ProLiant hosts.";
      }
    ];

    # In-band IPMI (/dev/ipmi0) for the iLO sensor check.
    boot.kernelModules = [
      "ipmi_devintf"
      "ipmi_si"
    ];
    environment.systemPackages = [ pkgs.ipmitool ];

    systemd.services.gen9-t4-ocsd-workload = lib.mkIf (cfg.workloadUnits == [ ]) {
      description = "Placeholder for GPU workloads the OCSD bridge may stop";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.coreutils}/bin/true";
      };
    };

    systemd.services.gen9-t4-ocsd = {
      description = "iLO 4 OCSD thermal bridge for an NVIDIA GPU (${cfg.profile})";
      wantedBy = [ "multi-user.target" ];
      after = [ "nvidia-persistenced.service" ];
      wants = [ "nvidia-persistenced.service" ];
      startLimitIntervalSec = 300;
      startLimitBurst = 5;
      environment = {
        OCSD_NVIDIA_SMI = toString cfg.nvidiaSmi;
        OCSD_IPMITOOL = lib.getExe pkgs.ipmitool;
        OCSD_SYSTEMCTL = "${config.systemd.package}/bin/systemctl";
        OCSD_WORKLOAD_UNITS = lib.concatStringsSep " " workloadUnits;
        OCSD_PROFILE = cfg.profile;
        OCSD_PUBLISH_OFFSET_C = toString cfg.publishOffset;
        OCSD_ILO_OFFSET_C = toString (cfg.iloDisplayOffset + cfg.publishOffset);
      }
      // lib.optionalAttrs (cfg.iloSensor != null) { OCSD_ILO_SENSOR = cfg.iloSensor; };
      serviceConfig = {
        # Type=exec, not notify: READY is sent only once iLO confirms the sensor,
        # which after a power cycle needs an iLO reset. Type=notify would hold boot
        # and nixos-rebuild switch in "activating", then time out and restart-loop.
        # The daemon publishes (and pings the watchdog) before iLO confirms; the
        # READY STATUS text appears in systemctl status once it does.
        Type = "exec";
        NotifyAccess = "main";
        ExecStart = "${lib.getExe pkgs.python3} ${cfg.package}/libexec/gen9-t4-ocsd/gen9_t4_ocsd.py";
        Restart = "on-failure";
        RestartSec = 3;
        # One loop can block ~19 s (15 s IPMI timeout + 4 s nvidia-smi).
        WatchdogSec = 60;
        # Shutdown publishes cooldown for up to 90 s before restoring the table.
        TimeoutStopSec = 150;
        StateDirectory = "gen9-t4-ocsd";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "gen9-t4-ocsd";
        RuntimeDirectoryMode = "0700";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        RestrictAddressFamilies = [ "AF_UNIX" ];
        DevicePolicy = "closed";
        DeviceAllow = [
          "/dev/mem rw"
          "/dev/ipmi0 rw"
          "/dev/nvidia0 rw"
          "/dev/nvidiactl rw"
          "/dev/nvidia-uvm rw"
        ];
        MemoryMax = "128M";
        TasksMax = 32;
      };
    };
  };
}
