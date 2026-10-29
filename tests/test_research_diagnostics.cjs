const {test} = require('node:test');
const assert = require('node:assert/strict');
const {researchErrorMessage} = require('../frontend/research.js');
test('TikTok diagnostic codes have understandable public messages', () => {
    assert.match(researchErrorMessage('source_structure_changed'), /No se reconocieron.*diagnóstico del trabajador/);
    assert.match(researchErrorMessage('access_restricted'), /restricción de acceso/);
    assert.match(researchErrorMessage('browser_unavailable'), /completar la carga/);
    assert.match(researchErrorMessage('source_load_timeout'), /no terminó de cargar.*tiempo permitido/);
    assert.equal(researchErrorMessage(null), '—');
});
