{ runAllTests ? false }:

with import <nixpkgs> {};

python3Packages.buildPythonApplication (rec {
  name = "nixpart-${version}";
  version = "1.0.0";

  src = ./.;

  checkInputs = [ nix ];
  propagatedBuildInputs = [ python3Packages.blivet ];
  makeWrapperArgs = [ "--set GI_TYPELIB_PATH \"$GI_TYPELIB_PATH\"" ];
} // lib.optionalAttrs runAllTests {
  NIX_PATH = "nixpkgs=${<nixpkgs>}";
})
