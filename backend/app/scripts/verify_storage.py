"""Confere se tudo o que o banco referencia existe no armazenamento de objetos.

Para cada original não expurgado, versão publicada (dados e rejeitados) e exportação pronta,
verifica se o objeto existe e tem o tamanho registrado; com `--deep`, baixa e confere o SHA-256
(originais e dados das versões). Usado depois de restaurar um backup: banco e bucket precisam ser
do mesmo ponto no tempo.

    python -m app.scripts.verify_storage            # existência e tamanho
    python -m app.scripts.verify_storage --deep     # e hashes

Sai com código 1 se faltar algum objeto ou algo não conferir. Só imprime identificadores.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from botocore.exceptions import ClientError
from sqlalchemy import select

from app.core.db import session_scope
from app.core.logging import configure_logging
from app.models import DatasetVersion, ExportJob, ExportStatus, Upload
from app.processing.pipeline import file_sha256
from app.services import storage


def _size(key: str) -> int | None:
    try:
        return int(storage.get_s3().head_object(Bucket=storage.bucket(), Key=key)["ContentLength"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _sha256(key: str, work: Path) -> str:
    target = work / "objeto"
    storage.download_file(key, target)
    try:
        return file_sha256(target)
    finally:
        target.unlink(missing_ok=True)


def verify(deep: bool) -> dict[str, object]:
    counts = {"uploads": 0, "versions": 0, "exports": 0, "hashes": 0}
    missing: list[str] = []
    mismatched: list[str] = []
    with session_scope() as db:
        uploads = db.execute(
            select(Upload.id, Upload.storage_key, Upload.size_bytes, Upload.sha256).where(
                Upload.purged_at.is_(None)
            )
        ).all()
        versions = db.execute(
            select(
                DatasetVersion.id,
                DatasetVersion.storage_key,
                DatasetVersion.size_bytes,
                DatasetVersion.checksum_sha256,
                DatasetVersion.rejected_storage_key,
            )
        ).all()
        exports = db.execute(
            select(ExportJob.id, ExportJob.storage_key, ExportJob.size_bytes).where(
                ExportJob.status == ExportStatus.SUCCEEDED, ExportJob.storage_key.is_not(None)
            )
        ).all()

    with tempfile.TemporaryDirectory(prefix="verify-") as tmp:
        work = Path(tmp)

        def check(kind: str, ident: object, key: str, size: int | None, sha: str | None) -> None:
            found = _size(key)
            if found is None:
                missing.append(f"{kind}:{ident}")
                return
            if size is not None and found != size:
                mismatched.append(f"{kind}:{ident}:tamanho")
                return
            if deep and sha:
                counts["hashes"] += 1
                if _sha256(key, work) != sha:
                    mismatched.append(f"{kind}:{ident}:sha256")

        for ident, key, size, sha in uploads:
            counts["uploads"] += 1
            check("upload", ident, key, size, sha)
        for ident, key, size, sha, rejected in versions:
            counts["versions"] += 1
            check("versao", ident, key, size, sha)
            if rejected:
                check("rejeitados", ident, rejected, None, None)
        for ident, export_key, export_size in exports:
            counts["exports"] += 1
            if export_key:  # filtrado na consulta; a coluna é anulável
                check("exportacao", ident, export_key, export_size, None)
    return {**counts, "missing": missing, "mismatched": mismatched}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deep", action="store_true", help="confere também o SHA-256")
    args = parser.parse_args()
    configure_logging("WARNING")
    result = verify(args.deep)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["missing"] or result["mismatched"] else 0


if __name__ == "__main__":
    sys.exit(main())
