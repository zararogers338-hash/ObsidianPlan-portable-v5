"""MUC — MICP Ureolysis Chemistry engine package.

Modules:
  errors     — typed error taxonomy (MUC-E1xxx/E2xxx/E3xxx/E4xxx)
  units      — dimensional analysis and unit validation
  constants  — thermodynamic constants with temperature corrections
  activity   — Davies activity-coefficient model
  speciate   — carbonate equilibrium, pH solve, saturation index
  kinetics   — urease-catalyzed urea hydrolysis rate laws
  balance    — elemental & charge conservation checks
  simulate   — coupled batch ODE (kinetic vs equilibrium)
  sens       — OAT sensitivity and uncertainty propagation
  phreeqc    — PHREEQC input generation / output parsing adapter
"""

__version__ = "1.0.0"
