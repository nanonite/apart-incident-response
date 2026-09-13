{
  description = "Reproducible report tooling for apart-incident-response";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = [
              pkgs.just
              pkgs.biber
              (pkgs.texlive.combine {
                inherit (pkgs.texlive)
                  scheme-medium
                  algorithm2e algorithmicx algorithms
                  biblatex biblatex-apa babel booktabs
                  changepage cleveref cmbright cm-super colortbl csquotes
                  datetime dblfloatfix enumitem epstopdf
                  float fmtcount hyphenat hypcap hyperref
                  inconsolata lipsum mhchem montserrat multirow
                  pdfpages placeins relsize setspace siunitx
                  soul subfigure textgreek titlesec tipa sttools upquote;
              })
            ];
          };
        });
    };
}
