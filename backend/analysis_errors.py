"""Allowlisted diagnostics: never log exception messages, prompts or provider bodies."""

import logging
from uuid import uuid4

from openai import (APITimeoutError, APIConnectionError, AuthenticationError,
                    PermissionDeniedError, RateLimitError, BadRequestError, NotFoundError)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MESSAGES = {
    'configuration': 'El servidor no pudo configurar el cliente de OpenAI. Revisa la configuración local.',
    'authentication': 'OpenAI rechazó las credenciales o los permisos del servidor.',
    'rate_limit': 'OpenAI informó un límite de uso o cuota. Revisa el consumo antes de reintentar.',
    'timeout': 'OpenAI no respondió dentro del tiempo permitido. No se reintentó automáticamente.',
    'connection': 'No se pudo conectar con OpenAI. No se reintentó automáticamente.',
    'model_unavailable': 'El modelo configurado no está disponible para esta cuenta.',
    'invalid_schema': 'OpenAI rechazó el esquema de salida estructurada configurado en el servidor.',
    'invalid_request': 'OpenAI rechazó la solicitud. Consulta la referencia técnica en el servidor.',
    'output_truncated': 'OpenAI agotó el límite de salida antes de completar el JSON. No se guardó un análisis parcial.',
    'output_refused': 'OpenAI no pudo analizar este contenido. No se guardaron hallazgos.',
    'output_incomplete': 'OpenAI devolvió una respuesta incompleta. No se guardaron hallazgos.',
    'output_validation': 'La respuesta de OpenAI no cumple el esquema o sus evidencias no coinciden con las publicaciones.',
    'output_json': 'OpenAI devolvió un JSON ilegible. No se guardó un análisis.',
    'output_schema': 'La estructura recibida no permite recuperar un análisis verificable.',
    'evidence_reference': 'Las referencias recibidas no corresponden a las publicaciones enviadas.',
    'evidence_coverage': 'Faltan citas verificables para las publicaciones de respaldo.',
    'evidence_quote': 'Las citas recibidas no aparecen en los textos originales.',
    'evidence_text': 'El hallazgo recibido no contiene texto válido.',
    'evidence_missing': 'No se encontraron hallazgos con respaldo verificable. No se guardó el análisis.',
    'storage': 'No se pudo confirmar el guardado del análisis en MongoDB. Consulta el estado antes de reintentar.',
    'provider': 'No se pudo completar la solicitud a OpenAI. Consulta la referencia técnica en el servidor.',
}


class ResponseProblem(ValueError):
    def __init__(self, code):
        self.code = code


class AnalysisFailure(RuntimeError):
    def __init__(self, code, stage='provider'):
        self.code = code if code in MESSAGES else 'provider'
        self.stage = stage
        self.reference = str(uuid4())
        self.status_code = {'rate_limit': 429, 'timeout': 504, 'storage': 503,
                            'configuration': 503, 'authentication': 503}.get(self.code, 502)
        super().__init__(MESSAGES[self.code])

    def public(self):
        return {'code': self.code, 'message': str(self), 'reference': self.reference}


def safe_validation_issues(error):
    """Expose schema paths/types, never values, arbitrary keys or exception text."""
    fields = {'summary', 'themes', 'communication_style', 'text', 'name', 'description',
              'publication_ids', 'publication_id', 'evidence', 'quote', 'dimensions', 'dimension', 'indicators'}
    return [{'type': item['type'], 'path': [part if isinstance(part, int) or part in fields else '<field>'
                                           for part in item['loc']]}
            for item in error.errors(include_input=False, include_context=False)][:10]


def diagnostic(error, stage, model):
    if isinstance(error, ResponseProblem):
        code = error.code
    elif stage == 'storage':
        code = 'storage'
    elif isinstance(error, APITimeoutError):
        code = 'timeout'
    elif isinstance(error, AuthenticationError) or isinstance(error, PermissionDeniedError):
        code = 'authentication'
    elif isinstance(error, RateLimitError):
        code = 'rate_limit'
    elif isinstance(error, NotFoundError):
        code = 'model_unavailable'
    elif isinstance(error, BadRequestError):
        provider_code = getattr(error, 'code', None)
        code = 'invalid_schema' if provider_code == 'invalid_json_schema' else (
            'model_unavailable' if provider_code == 'model_not_found' else 'invalid_request')
    elif isinstance(error, APIConnectionError):
        code = 'connection'
    elif stage == 'validation' or isinstance(error, ValidationError):
        code = 'output_validation'
    elif stage == 'configuration':
        code = 'configuration'
    else:
        code = 'provider'
    failure = AnalysisFailure(code, stage)
    if isinstance(error, ValidationError):
        logger.warning('analysis_schema reference=%s issues=%s', failure.reference, safe_validation_issues(error))
    status = getattr(error, 'status_code', None)
    status = status if isinstance(status, int) else None
    provider_code = getattr(error, 'code', None)
    if provider_code not in {'invalid_json_schema', 'model_not_found', 'unsupported_parameter', 'unsupported_value',
                             'invalid_value', 'insufficient_quota', 'rate_limit_exceeded'}:
        provider_code = None
    parameter = getattr(error, 'param', None)
    if parameter not in {'model', 'reasoning.effort', 'max_output_tokens', 'text.format', 'text.format.schema'}:
        parameter = None
    logger.warning('analysis_failure reference=%s stage=%s category=%s model=%s exception_type=%s http_status=%s provider_code=%s parameter=%s',
                   failure.reference, stage, failure.code, model, type(error).__name__, status, provider_code, parameter)
    return failure
