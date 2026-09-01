from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / "scripts" / "phase1" / "deploy_linux.sh"


def test_linux_deployer_grants_only_the_pinned_runtime_uid_read_acl() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "rustfs_secret_reader_uid=10001" in script
    assert 'setfacl -m "u:${reader_uid}:r--,m::r--"' in script
    assert "group::---" in script
    assert "other::---" in script
    assert 'user:"$reader_uid":r--' in script
    assert "secret has an unexpected ACL entry" in script

    for secret_variable in (
        "PHASE1_RUSTFS_ACCESS_KEY_FILE",
        "PHASE1_RUSTFS_SECRET_KEY_FILE",
        "PHASE1_RUSTFS_SSE_MASTER_KEY_FILE",
    ):
        invocation = script.split(f"managed_secret \\\n  {secret_variable}", maxsplit=1)[1]
        assert '"$rustfs_secret_reader_uid"' in invocation.split("managed_secret", maxsplit=1)[0]


def test_linux_deployer_preflights_each_actual_secret_consumer() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    rustfs_probe = script.split(
        "compose run --rm --no-deps --entrypoint /bin/sh rustfs", maxsplit=1
    )[1].split("compose run", maxsplit=1)[0]
    assert 'if [ "$actual_uid" != "10001" ]' in rustfs_probe
    assert "/run/secrets/rustfs_access_key" in rustfs_probe
    assert "/run/secrets/rustfs_secret_key" in rustfs_probe
    assert "/run/secrets/rustfs_sse_s3_master_key" in rustfs_probe

    storage_init_probe = script.split(
        "compose run --rm --no-deps --entrypoint /bin/sh storage-init", maxsplit=1
    )[1].split("printf 'Starting Crash-Cap services", maxsplit=1)[0]
    assert 'if [ "$actual_uid" != "10001" ]' in storage_init_probe
    assert "/run/secrets/rustfs_access_key" in storage_init_probe
    assert "/run/secrets/rustfs_secret_key" in storage_init_probe
    assert "/run/secrets/rustfs_sse_s3_master_key" not in storage_init_probe


def test_linux_deployer_keeps_non_rustfs_secrets_on_private_mode_path() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert (
        "managed_secret PHASE1_POSTGRES_PASSWORD_FILE postgres_password password "
        '"$postgres_volume"'
    ) in script
    assert (
        "managed_secret PHASE1_REDIS_PASSWORD_FILE redis_password password "
        '"$redis_volume"'
    ) in script
    assert 'if [[ -n "$reader_uid" ]]; then' in script
    assert "else\n    assert_private_file \"$file_path\"" in script
    assert 'chmod 0600 "$PHASE1_RUNTIME_ENV_FILE"' in script
