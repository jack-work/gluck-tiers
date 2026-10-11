{
  description = "gluck-tiers — a tier list behind kelliher-web";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    gluck-service-lib.url = "github:jack-work/gluck-service-lib";
    gluck-service-lib.inputs.nixpkgs.follows = "nixpkgs";
    zanni.url = "github:jack-work/zanni";
    zanni.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { self, nixpkgs, gluck-service-lib, zanni, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = nixpkgs.lib.genAttrs systems;

      pyFor = pkgs: pkgs.python3.withPackages (ps: with ps; [ flask waitress boto3 ]);

      # doc/packaging.md. mkPythonService's ExecStart is
      # `python ${entrypoint}`, and a bare ./tiers/main.py copies that ONE
      # file into the store, so every sibling import fails at startup while
      # the test suite stays green. The app is therefore a derivation holding
      # the whole tree, and entrypoint points inside it.
      # www/ is built by another aria in parallel. A nix path literal to a
      # missing file fails at EVALUATION, not in the shell guard, so the
      # existence test has to happen here.
      boardSrc = ./www/board.html.in;
      hasBoard = builtins.pathExists boardSrc;

      mkApp =
        pkgs:
        let
          py = pyFor pkgs;
        in
        pkgs.stdenv.mkDerivation {
          pname = "gluck-tiers";
          version = "0.1.0";
          src = ./.;
          nativeBuildInputs = [ zanni.packages.${pkgs.stdenv.hostPlatform.system}.default ];
          dontConfigure = true;
          dontBuild = true;
          installPhase = ''
            runHook preInstall
            mkdir -p $out $out/templates

            for f in tiers/*.py; do cp "$f" $out/; done

            # The unit suite runs against the SOURCE tree, where every module
            # is present by construction. It is deliberately NOT the packaging
            # check: this estate has watched a suite like this stay green while
            # the shipped unit died at import.
            TIERS_EXAMPLES=$PWD/examples PYTHONDONTWRITEBYTECODE=1 \
              ${py}/bin/python tiers/tests/test_parse.py

            # The packaging check imports from $out ALONE, so it fails when a
            # module the entrypoint needs did not ship. doc/packaging.md holds
            # the negative control that proves it can fail.
            # PYTHONDONTWRITEBYTECODE, or this very check writes a
            # __pycache__ into the artifact it is checking. A .pyc in a
            # shipped tree can shadow the module it was built from, which is
            # the failure this check exists to catch, arriving by another door.
            ( cd $out && PYTHONPATH=$out PYTHONDONTWRITEBYTECODE=1 ${py}/bin/python -c "
import main, parse, mirror, store
assert hasattr(main, 'app'), 'main exposes no app'
print('packaging ok: every entrypoint import resolves inside the shipped tree')
" )
          ''
          + (
            if hasBoard then
              ''
                zanni-inline \
                  --component heft --component gesso --component fontpack \
                  --component boil --component phosphor \
                  ${boardSrc} -o $out/templates/board.html
                zanni-check $out/templates/board.html

                # Caddy reverse-proxies EVERYTHING for this host and runs no
                # file_server, and Flask routes only /, /api/* and /img/<sha>.
                # So a second request for board.js can never be served: the
                # page loaded 200 while its script 404'd and nothing ran. The
                # script is therefore inlined, the same reason zanni-inline
                # inlines its filter defs: no second request to get wrong.
                PYTHONDONTWRITEBYTECODE=1 ${py}/bin/python ${./tiers/inline_assets.py} \
                  $out/templates/board.html ${./www}

                # Fetch the page through the real app and demand every asset
                # it still references answers 200. "/ returns 200" was taken
                # as evidence the board worked; it only ever proved the
                # template built.
                ( cd $out && PYTHONPATH=$out PYTHONDONTWRITEBYTECODE=1 \
                  TIERS_TEMPLATES=$out/templates \
                  TIERS_DEFAULT_SLUG=asset-check \
                  ${py}/bin/python ${./tiers/tests/test_assets.py} )
              ''
            else
              ''
                echo "www/board.html.in absent: shipping without a board template" >&2
              ''
          )
          + ''
            runHook postInstall
          '';
        };

      serviceModule =
        { config, lib, pkgs, ... }:
        let
          app = mkApp pkgs;
        in
        lib.mkMerge [
          (gluck-service-lib.lib.mkPythonService {
            inherit config lib pkgs;
            name = "gluck-tiers";
            subdomain = "tiers";
            port = 9104;
            entrypoint = "${app}/main.py";
            pythonPackages = ps: with ps; [ flask waitress boto3 ];
            stateDirectory = "gluck-tiers";
            requireAuth = true;
            requiredGroups = [ "gluck-tiers-admin" ];
            environment = {
              TIERS_TEMPLATES = "${app}/templates";
              TIERS_BUCKET = "files";
              TIERS_PREFIX = "tiers/";
              TIERS_S3_ENDPOINT = "http://127.0.0.1:3900";
              TIERS_S3_REGION = "spain";
            };
            # Interpolated, never typed. A literal path can drift from the
            # declaration in spain-flake; this cannot. restartUnits on the
            # sops secret is what makes a key rotation actually reach the
            # running process.
            extraServiceConfig = {
              LoadCredential = [
                "garage:${config.sops.secrets.gluck-tiers-garage-credentials.path}"
              ];
            };
          })
        ];
    in
    {
      packages = forAll (system: {
        default = mkApp nixpkgs.legacyPackages.${system};
      });

      nixosModules.default = serviceModule;
      nixosModules.gluck-tiers = serviceModule;

      devShells = forAll (system: {
        default = nixpkgs.legacyPackages.${system}.mkShell {
          packages = [ (pyFor nixpkgs.legacyPackages.${system}) ];
        };
      });

      checks = forAll (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          py = pyFor pkgs;
        in
        {
          app = mkApp pkgs;

          # The negative control, kept rather than performed once. It ships
          # the tree MINUS one module and asserts the import FAILS. If this
          # derivation ever succeeds at importing, the packaging check in
          # mkApp proves nothing and this build says so.
          packaging-negative-control = pkgs.runCommand "gluck-tiers-packaging-negative-control"
            { src = ./.; }
            ''
              mkdir -p broken
              for f in $src/tiers/*.py; do
                case "$(basename $f)" in
                  mirror.py) echo "omitting mirror.py from the shipped tree" ;;
                  *) cp "$f" broken/ ;;
                esac
              done
              if PYTHONPATH=$PWD/broken ${py}/bin/python -c "import main" 2>err.txt; then
                echo "FAIL: main imported with mirror.py absent, so the packaging check cannot catch a missing module"
                exit 1
              fi
              grep -q "No module named 'mirror'" err.txt || {
                echo "FAIL: import broke for the wrong reason:"; cat err.txt; exit 1; }
              echo "ok: shipping without mirror.py fails the import, as it must"
              cat err.txt | tail -1
              touch $out
            '';
        }
      );
    };
}
