"""Deterministic descriptive first-significant-digit analysis; no I/O."""
from decimal import Decimal
import math

METRICS = {
    'views': 'Visualizaciones', 'likes': 'Me gusta', 'comments_count': 'Comentarios',
    'shares': 'Compartidos', 'saves': 'Guardados',
}
DISCLAIMER = ('Una desviación respecto de Benford no demuestra bots, fraude, compra de seguidores '
              'ni manipulación. Una distribución cercana tampoco demuestra autenticidad.')


def benford_probabilities():
    return [math.log10(1 + 1 / digit) for digit in range(1, 10)]


def numeric_value(value):
    """Accept original finite numbers, never booleans or display abbreviations."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = Decimal(str(value))
    return number if number.is_finite() else None


def first_significant_digit(value):
    number = numeric_value(value)
    if number is None or number <= 0:
        return None
    return number.as_tuple().digits[0]


def analyze_values(values):
    counts = [0] * 9
    excluded = dict(missing=0, zero=0, negative=0, invalid=0)
    exponents = []
    for value in values:
        number = numeric_value(value)
        if value is None:
            excluded['missing'] += 1
        elif number is None:
            excluded['invalid'] += 1
        elif number == 0:
            excluded['zero'] += 1
        elif number < 0:
            excluded['negative'] += 1
        else:
            counts[first_significant_digit(number) - 1] += 1
            exponents.append(number.adjusted())
    n = sum(counts)
    probabilities = benford_probabilities()
    distribution = []
    for digit, (count, probability) in enumerate(zip(counts, probabilities), 1):
        observed = count / n if n else None
        distribution.append(dict(digit=digit, observed_count=count, expected_count=n * probability,
            observed_probability=observed, theoretical_probability=probability,
            observed_percent=100 * observed if n else None, theoretical_percent=100 * probability,
            difference_percentage_points=100 * (observed - probability) if n else None))
    mad = math.fsum(abs(row['observed_probability'] - row['theoretical_probability'])
                    for row in distribution) / 9 if n else None
    chi = math.fsum((row['observed_count'] - row['expected_count']) ** 2 / row['expected_count']
                    for row in distribution) if n else None
    low = [row['digit'] for row in distribution if row['expected_count'] < 5]
    span = max(exponents) - min(exponents) if n else None
    warnings = []
    if not n:
        warnings.append('No hay valores numéricos positivos válidos para analizar.')
    if low:
        warnings.append('Muestra reducida: hay recuentos esperados menores que 5. χ² es solo descriptivo; no se interpreta significación estadística.')
    if span is not None and span < 2:
        warnings.append('Los valores abarcan menos de dos saltos de orden de magnitud; esto limita la pertinencia de Benford y no constituye un criterio de aceptación.')
    warnings.append('La selección de publicaciones, su dependencia, los límites naturales y el posible redondeo de las métricas no permiten asumir que esta muestra deba seguir Benford.')
    interpretation = f'Se analizaron {n} observaciones válidas y se excluyeron {sum(excluded.values())} registros.'
    if n:
        largest = max(distribution, key=lambda row: abs(row['difference_percentage_points']))
        interpretation += (f" La mayor diferencia absoluta corresponde al dígito {largest['digit']} "
            f"({abs(largest['difference_percentage_points']):.2f} puntos porcentuales). "
            f'MAD = {mad:.6f} es el promedio de diferencias absolutas entre probabilidades, en escala 0–1. '
            f'χ² = {chi:.6f} pondera las diferencias de recuentos por sus frecuencias esperadas; depende del tamaño de muestra. '
            'No se aplican categorías de cumplimiento ni umbrales de fraude.')
    return dict(status='exploratory' if n else 'empty', total_records=n + sum(excluded.values()),
        valid_records=n, excluded_records=sum(excluded.values()), exclusions=excluded,
        distribution=distribution, mad=mad, chi_squared=chi, degrees_of_freedom=8,
        expected_counts_sufficient=bool(n and not low), low_expected_digits=low,
        p_value=None, inference_performed=False, orders_spanned=span, warnings=warnings,
        interpretation=interpretation, disclaimer=DISCLAIMER)
