#!/usr/bin/env bash
# Backup consistente da instalação do docker-compose.prod.yml: banco (pg_dump) e objetos (volume
# do MinIO) do mesmo ponto no tempo. Para API, worker, beat e MinIO durante a cópia, para que
# nada seja gravado entre o dump e o arquivo dos objetos; depois sobe tudo de novo.
#
#   scripts/backup.sh [diretório]        # padrão: backups/AAAAMMDD-HHMMSS
#
# Rode na pasta do projeto, com o mesmo .env usado no deploy. Restauração: scripts/restore.sh.
set -euo pipefail

compose=(docker compose -f "${COMPOSE_FILE:-docker-compose.prod.yml}")
project="$("${compose[@]}" config | sed -n 's/^name: //p' | head -n 1)"
dest="${1:-backups/$(date -u +%Y%m%d-%H%M%S)}"
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"

restart() {
  echo "Subindo os serviços de novo…"
  "${compose[@]}" up -d --wait --wait-timeout 300
}
trap restart EXIT

echo "Parando API, worker, beat e MinIO (o site fica indisponível durante a cópia)…"
"${compose[@]}" stop api worker beat minio

echo "Banco: pg_dump em formato custom…"
"${compose[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  >"$dest/postgres.dump"

echo "Objetos: volume ${project}_miniodata…"
docker run --rm -v "${project}_miniodata:/data:ro" -v "$dest:/backup" busybox:1.37 \
  tar -czf /backup/minio.tar.gz -C /data .

(cd "$dest" && sha256sum postgres.dump minio.tar.gz >SHA256SUMS)
cat >"$dest/MANIFEST" <<EOF
projeto=$project
criado_em=$(date -u +%Y-%m-%dT%H:%M:%SZ)
commit=$(git rev-parse --short HEAD 2>/dev/null || echo desconhecido)
EOF
echo "Backup em $dest:"
ls -l "$dest"
