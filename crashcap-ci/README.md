# Crash-Cap file upload

Upload EXE, DLL, PDB and DMP files into an explicit Workspace, or upload artifacts and symbols into the public area. The server verifies each file independently and pairs PE/PDB by their real identities. No Git checkout, project configuration, Build registration, manifest or complete batch is required.

```powershell
crashcap upload .\Release --workspace light-streamer --build-version 11.0.1.27
crashcap upload .\sdk.dll .\sdk.pdb --public --build-version 3.2
crashcap upload .\crash.dmp --workspace light-streamer
```

The target is a Workspace ID or exact name. Public batches cannot contain DMP. `--build-version` is optional; `crashcap --version` displays the program version. Directories are scanned recursively. Add `--api-url http://host:8080/api/v3`, or set `CRASHCAP_API_URL`. Add `--json --receipt crashcap-upload.json` for automation.

The command waits for file acceptance. A retained PE or PDB awaiting its counterpart is successful. A failed file does not undo successful files; the exit code is nonzero and the receipt retains each result and its resource links. Retrying a DMP preserves its existing nonempty version and reports a differing submitted label. Edit the DMP version in its report to change lists and statistics without reanalysis.

The browser offers the same upload flow, optional batch version, inline Workspace creation and a searchable artifact inventory. Workspace pages automatically target that Workspace.

Only files in a consumer Workspace and public files are candidates. Content reuse does not share private symbols across Workspaces. Same identity with different valid contents is an explicit conflict. Public and private halves can combine only in the private half's Workspace.

Build with `cargo build --release -p crashcap`. The historical source directory name remains `crashcap-ci`; its sole executable is `crashcap`.
