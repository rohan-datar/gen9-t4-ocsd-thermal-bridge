{
  description = "iLO 4 OCSD thermal bridge for an NVIDIA GPU in a ProLiant ML350 Gen9";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      forSystems = nixpkgs.lib.genAttrs [ "x86_64-linux" ];
    in
    {
      packages = forSystems (system: rec {
        gen9-t4-ocsd = nixpkgs.legacyPackages.${system}.callPackage ./nix/package.nix { };
        default = gen9-t4-ocsd;
      });

      # Building the package runs the offline test suite.
      checks = forSystems (system: {
        gen9-t4-ocsd = self.packages.${system}.gen9-t4-ocsd;
      });

      nixosModules = {
        gen9-t4-ocsd = ./nix/module.nix;
        default = self.nixosModules.gen9-t4-ocsd;
      };

      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
