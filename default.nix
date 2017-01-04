{ runAllTests ? false, system ? builtins.currentSystem }:

with import <nixpkgs> {};

let
  drv = python3Packages.buildPythonApplication (rec {
    name = "nixpart-${version}";
    version = "1.0.0";

    src = ./.;

    checkInputs = [ nix ];
    propagatedBuildInputs = [ python3Packages.blivet ];
    makeWrapperArgs = [ "--set GI_TYPELIB_PATH \"$GI_TYPELIB_PATH\"" ];
  } // lib.optionalAttrs runAllTests {
    NIX_PATH = "nixpkgs=${<nixpkgs>}";
  });

  inherit (import <nixpkgs/nixos/lib/testing.nix> {
    inherit system;
  }) runInMachine;

in if runAllTests then runInMachine {
  inherit drv;
  machine = { lib, pkgs, ... }: {
    nix.binaryCaches = lib.mkForce [];
    system.extraDependencies = [ pkgs.stdenv ];
  };
} else drv
