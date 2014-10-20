{ nixpart ? { outPath = ./.; revCount = 1234; shortRev = "abcdef"; }
, officialRelease ? false
}:

let
  pkgs = import <nixpkgs> {};

  baseVer = import (pkgs.runCommand "version.nix" {} ''
    sed -ne "s/.*version='\\([^']*\\)'.*/\"\\1\"/p" ${./setup.py} > "$out"
  '');
  preVersion = "pre${toString nixpart.revCount}_${nixpart.shortRev}";
  version = baseVer + pkgs.lib.optionalString (!officialRelease) preVersion;


in rec {
  tarball = pkgs.releaseTools.sourceTarball {
    name = "nixpart-tarball";
    inherit version officialRelease;
    src = nixpart;

    buildInputs = [ pkgs.git ];

    distPhase = ''
      releaseName="nixpart-$VERSION"
      mkdir -p "$out/tarballs"
      git config user.email "dirty@working.dir"
      git config user.name "Dirty Changes"
      git commit -am "Add uncommitted changes from working tree."
      git archive --format=tar --prefix="$releaseName/" HEAD \
        | xz > "$out/tarballs/$releaseName.tar.xz"
    '';
  };

  build = pkgs.lib.genAttrs [ "i686-linux" "x86_64-linux" ] (system: let
    inherit (import <nixpkgs> { inherit system; }) pythonPackages;
  in pythonPackages.buildPythonPackage rec {
    name = "nixpart-${version}";
    namePrefix = "";

    src = "${tarball}/tarballs/nixpart-${version}.tar.xz";

    buildInputs = [ pythonPackages.blivet ];
  });
}
