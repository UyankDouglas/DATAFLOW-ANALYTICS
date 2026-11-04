#!/usr/bin/env bash
# Restaura um backup de scripts/backup.sh na instalação do docker-compose.prod.yml.
#
#   scripts/restore.sh <diretório do backup> --yes
#
# IMPACTO: substitui o banco inteiro e todos os objetos do MinIO pelos do backup. Tudo o que foi
# gravado depois do backup (contas, datasets, versões, exportações, auditoria) é perdido. Sem
# --yes, o script só mostra o que faria. Depois de restaurar, confere cada objeto referenciado
# pelo banco (tamanho e SHA-256) e sai com erro se faltar algum.
set -euo pipefail

src="${1:?informe o diretório do backup}"
confirm="${2:-}"
compose=(docker compose -f "${COMPOSE_FILE:-docker-compose.prod.yml}")
project="$("${compose[@]}" config | sed -n 's/^name: //p' | head -n 1)"
src="$(cd "$src" && pwd)"

(cd "$src" && sha256sum --check --quiet SHA256SUMS)
echo "Backup íntegro: $src"
cat "$src/MANIFEST" 2>/dev/null || true
echo
echo "Isto vai SUBSTITUIR o banco e os objetos do projeto '$project' pelos do backup."
if [[ "$confirm" != "--yes" ]]; then
  echo "Nada foi alterado. Repita com --yes para restaurar."
  exit 2
fi

echo "Parando API, worker, beat, MinIO e o proxy…"
"${compose[@]}" stop web api worker beat minio
"${compose[@]}" up -d --wait postgres

echo "Banco: pg_restore --clean (recria cada tabela do backup)…"
"${compose[@]}" exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error --single-transaction' \
  <"$src/postgres.dump"

echo "Objetos: substituindo o volume ${project}_miniodata…"
docker run --rm -v "${project}_miniodata:/data" -v "$src:/backup:ro" busybox:1.37 sh -c \
  'rm -rf /data/* /data/.[!.]* /data/..?* && tar -xzf /backup/minio.tar.gz -C /data && chown -R 65532:65532 /data'

echo "Subindo os serviços…"
"${compose[@]}" up -d --wait --wait-timeout 300

echo "Conferindo os objetos referenciados pelo banco…"
"${compose[@]}" exec -T api python -m app.scripts.verify_storage --deep
echo "Restauração concluída."
