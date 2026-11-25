{
  lib,
  stdenvNoCC,
  python3,
}:
stdenvNoCC.mkDerivation {
  pname = "gen9-t4-ocsd";
  version = "0-unstable-2026-11-25";

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../gen9_t4_ocsd.py
      ../gen9_t4_ocsd_register.py
      ../ocsd_discovery.py
      ../tests
      ../examples
      ../LICENSE
    ];
  };

  dontBuild = true;

  # Offline protocol tests: record layout, checksums, claim/restore, publish offset.
  doCheck = true;
  nativeCheckInputs = [ python3 ];
  checkPhase = ''
    runHook preCheck
    python3 -m unittest discover -s tests
    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall
    install -Dm0444 gen9_t4_ocsd.py $out/libexec/gen9-t4-ocsd/gen9_t4_ocsd.py
    install -Dm0444 LICENSE $out/share/doc/gen9-t4-ocsd/LICENSE
    runHook postInstall
  '';

  meta = {
    description = "iLO 4 OCSD thermal bridge: publishes an NVIDIA GPU temperature to HPE Gen9 fan control";
    homepage = "https://github.com/rohan-datar/gen9-t4-ocsd-thermal-bridge";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
