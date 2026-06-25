#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/import_zeninvest_dataset.sh --host HOST --user USER [options]

Options:
  --host HOST             SSH host for the VPS. Required.
  --user USER             SSH user for the VPS. Required.
  --port PORT             SSH port. Default: 22.
  --key PATH              Optional SSH private key path.
  --version VERSION       Dataset version. Default: v6.
  --remote-root PATH      Remote repo root. Default: /home/deploy_invest_ai/investment-agent.
  --dest PATH             Local staging dir. Default: data/zeninvest_imports/<version>.
  -h, --help              Show this help.

The script copies only the expected dataset files and does not store SSH
connection details in the repository.
EOF
}

ssh_host=""
ssh_user=""
ssh_port="22"
ssh_key=""
version="v6"
remote_root="/home/deploy_invest_ai/investment-agent"
dest=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      ssh_host="${2:-}"
      shift 2
      ;;
    --user)
      ssh_user="${2:-}"
      shift 2
      ;;
    --port)
      ssh_port="${2:-}"
      shift 2
      ;;
    --key)
      ssh_key="${2:-}"
      shift 2
      ;;
    --version)
      version="${2:-}"
      shift 2
      ;;
    --remote-root)
      remote_root="${2:-}"
      shift 2
      ;;
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ssh_host" || -z "$ssh_user" ]]; then
  echo "Missing required --host and/or --user." >&2
  usage >&2
  exit 2
fi

if [[ -z "$dest" ]]; then
  dest="data/zeninvest_imports/${version}"
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but was not found on PATH." >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh is required but was not found on PATH." >&2
  exit 1
fi

if [[ -n "$ssh_key" && ! -f "$ssh_key" ]]; then
  echo "SSH key does not exist: $ssh_key" >&2
  exit 1
fi

remote_dir="${remote_root%/}/data/learning/parquet/${version}"
mkdir -p "$dest"

ssh_args=(ssh -p "$ssh_port" -o IdentitiesOnly=yes)
if [[ -n "$ssh_key" ]]; then
  ssh_args+=(-i "$ssh_key")
fi
ssh_cmd="$(printf '%q ' "${ssh_args[@]}")"
ssh_cmd="${ssh_cmd% }"

rsync_args=(
  -az
  --prune-empty-dirs
  --include=decisions.parquet
  --include=features.parquet
  --include=outcomes.parquet
  --include=merged.parquet
  --include=text_corpus.parquet
  --include=rejected.parquet
  --include=schema.json
  --include=splits.json
  --exclude='*'
  -e "$ssh_cmd"
)

echo "Importing ZenInvest dataset ${version} into ${dest}"
rsync "${rsync_args[@]}" "${ssh_user}@${ssh_host}:${remote_dir}/" "${dest%/}/"
echo "Import complete. Staged files:"
find "$dest" -maxdepth 1 -type f | sort
