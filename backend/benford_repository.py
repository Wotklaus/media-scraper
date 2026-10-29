"""Read existing extraction snapshots or latest stored observation per publication."""
from .benford import METRICS, analyze_values
from .embedding_repository import EmbeddingRepository


class BenfordRepository:
    def __init__(self, database):
        self.database = database

    def analyze(self, username, metric='views', dataset='latest'):
        if metric not in METRICS or dataset not in ('latest', 'history'):
            raise ValueError('Parámetros de análisis inválidos.')
        username = EmbeddingRepository(self.database).profile(username)
        run = None
        if dataset == 'latest':
            run = self.database['extraction_runs'].find_one(
                {'profile_username_key': username.casefold(), 'status': 'saved'},
                {'_id': 0, 'run_id': 1, 'extracted_at': 1, 'snapshot.publications': 1},
                sort=[('extracted_at', -1), ('run_id', -1)])
            rows = (run.get('snapshot') or {}).get('publications', []) if run else []
            policy = 'Snapshot de la última extracción guardada; no se completa con publicaciones del historial.'
        else:
            rows = self.database['publications'].find(
                {'profile_username': username}, {'publication_id': 1, 'metrics': 1}
            ).sort([('last_seen_at', -1), ('last_run_id', -1), ('_id', -1)])
            policy = ('Una observación por publication_id: última observación almacenada, ordenada por '
                      'last_seen_at, last_run_id e _id descendentes. Se conserva incluso si su métrica es nula; '
                      'no se sustituye por una observación anterior. No se suman snapshots históricos.')
        seen, values = set(), []
        duplicates = invalid_ids = 0
        for row in rows:
            identity = row.get('publication_id')
            if not isinstance(identity, str) or not identity.strip():
                invalid_ids += 1
                continue
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            metrics = row.get('metrics')
            values.append(metrics.get(metric) if isinstance(metrics, dict) else None)
        result = analyze_values(values)
        if dataset == 'latest' and run is None:
            result['warnings'].insert(0, 'No hay una extracción registrada para este perfil. Puedes consultar el historial almacenado.')
        if invalid_ids:
            result['warnings'].append(f'{invalid_ids} registros sin ID válido omitidos antes del análisis.')
        return dict(username=username, metric=metric, metric_label=METRICS[metric], dataset=dataset,
            source_available=run is not None if dataset == 'latest' else bool(seen),
            run_id=run.get('run_id') if run else None,
            extracted_at=run.get('extracted_at') if run else None,
            selection_policy=policy, duplicates_removed=duplicates,
            invalid_publication_records=invalid_ids, **result)
