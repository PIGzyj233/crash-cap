#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL custom-format + standard S3 backup/restore helper. It is an
# operator runbook tool, not an automated disaster-recovery claim. The script
# never enables shell tracing and never prints secret values.

usage() {
  cat >&2 <<'EOF'
Usage:
  ops_backup_restore.sh backup <external-output-dir>
  ops_backup_restore.sh restore <external-backup-dir> --confirm "RESTORE <external-backup-dir>"

Required environment (set outside the repository):
  PGHOST PGPORT PGDATABASE PGUSER PG_PASSWORD_FILE
  S3_ENDPOINT S3_BUCKET S3_REGION S3_ACCESS_KEY_FILE S3_SECRET_KEY_FILE
  AWS CLI v2, pg_dump, and pg_restore on PATH
EOF
  exit 2
}

die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

[ "$#" -ge 2 ] || usage
action=$1
directory=$2
script_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(cd -- "$script_root/../.." && pwd -P)

case "$directory" in
  /*) target=$directory ;;
  *) target=$(cd -- "$(dirname -- "$directory")" && pwd -P)/$(basename -- "$directory") ;;
esac
case "$target" in
  "$repo_root"|"$repo_root"/*) die "backup target must be outside the repository" ;;
esac

command -v aws >/dev/null 2>&1 || die "aws CLI v2 is required"
command -v pg_dump >/dev/null 2>&1 || die "pg_dump is required"
command -v pg_restore >/dev/null 2>&1 || die "pg_restore is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
[ -n "${S3_ENDPOINT:-}" ] && [[ "$S3_ENDPOINT" == http://* ]] || die "S3_ENDPOINT must use http://"
s3_authority=${S3_ENDPOINT#http://}
s3_authority=${s3_authority%%/*}
[ -n "$s3_authority" ] && [[ "$s3_authority" != *"@"* ]] || die "S3_ENDPOINT must contain a host and no userinfo"
[[ "$S3_ENDPOINT" != *"?"* && "$S3_ENDPOINT" != *"#"* ]] || die "S3_ENDPOINT must not contain query or fragment"
[ -n "${S3_BUCKET:-}" ] || die "S3_BUCKET is required"
[ -r "${PG_PASSWORD_FILE:-}" ] || die "PG_PASSWORD_FILE must point to an external file"
[ -r "${S3_ACCESS_KEY_FILE:-}" ] || die "S3_ACCESS_KEY_FILE must point to an external file"
[ -r "${S3_SECRET_KEY_FILE:-}" ] || die "S3_SECRET_KEY_FILE must point to an external file"

export PGPASSWORD=$(<"$PG_PASSWORD_FILE")
export AWS_ACCESS_KEY_ID=$(<"$S3_ACCESS_KEY_FILE")
export AWS_SECRET_ACCESS_KEY=$(<"$S3_SECRET_KEY_FILE")
export AWS_DEFAULT_REGION=${S3_REGION:-us-east-1}

aws_s3() {
  aws --endpoint-url "$S3_ENDPOINT" --no-cli-pager "$@"
}

backup() {
  mkdir -p -- "$target/rustfs"
  pg_dump --format=custom --file "$target/postgres.dump"
  aws_s3 s3 sync "s3://$S3_BUCKET/" "$target/rustfs/" --no-progress --only-show-errors
  cp -- "$repo_root/deploy/compose/phase1.yml" "$target/phase1.yml"
  sha256sum "$target/postgres.dump" "$target/phase1.yml" > "$target/checksums.sha256"
  printf 'Backup created outside repository: %s\n' "$target"
  printf 'Backup contents: PostgreSQL custom dump, S3 object mirror, Compose policy, checksums.\n'
  printf 'Disaster-recovery drill status: NOT_PROVEN (run restore and record evidence separately).\n'
}

restore() {
  backup_dir=$1
  confirmation=$2
  [ -d "$target" ] || die "backup directory does not exist"
  [ -f "$target/postgres.dump" ] || die "backup is missing postgres.dump"
  [ -d "$target/rustfs" ] || die "backup is missing rustfs object mirror"
  [ -f "$target/checksums.sha256" ] || die "backup is missing checksums.sha256"
  expected="RESTORE $target"
  [ "$confirmation" = "$expected" ] || die "restore requires exact confirmation: $expected"
  (cd -- "$target" && sha256sum -c checksums.sha256)
  # --clean is intentionally explicit and the exact confirmation above is
  # required. S3 sync omits --delete so unknown destination objects are not
  # silently removed; an operator may review and clean them separately.
  pg_restore --clean --if-exists --no-owner --dbname "${PGDATABASE:?PGDATABASE is required}" "$target/postgres.dump"
  aws_s3 s3 sync "$target/rustfs/" "s3://$S3_BUCKET/" --sse AES256 --no-progress --only-show-errors
  printf 'Restore commands completed; verify Current Analysis, object hashes and statistics before service start.\n'
  printf 'Disaster-recovery drill status: NOT_PROVEN until an operator records read-back evidence.\n'
}

case "$action" in
  backup) [ "$#" -eq 2 ] || usage; backup ;;
  restore)
    [ "$#" -eq 4 ] || usage
    [ "$3" = "--confirm" ] || usage
    restore "$2" "$4"
    ;;
  *) usage ;;
esac
