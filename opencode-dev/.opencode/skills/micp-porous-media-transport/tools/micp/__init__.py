"""micp-porous-media-transport — MICP porous-media transport tools.

Modules
-------
errors         error-code taxonomy (OPM-E1xx..E8xx)
models         constants, enums, epistemic labels
units          quantity/unit/parameter validation (SI normalization)
dimensionless  Péclet / Damköhler / residence-time analysis
solver         deterministic 1D reactive-transport solver (operator splitting)
clogging       clogging criteria + Kozeny-Carman permeability coupling
validate       conservation/numerical/grid-sensitivity checks + schema validation
scenario       scenario normalization (raw dict -> SI solver config)
service        MicpService facade (the action pipeline)
observability  JSON-lines logging with a bounded ring buffer
"""
