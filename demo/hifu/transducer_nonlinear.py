#
# Nonlinear field generated in by a bowl-shaped HIFU transducer
# ==========================================================
#
# This demo illustrates how to:
#
# * Compute the nonlinear time-harmonic field in a homogeneous medium
# * Use incident field routines to generate the field from a HIFU transducer
# * Make a nice plot of the solution in the domain

import os
import sys
# FIXME: figure out how to avoid this sys.path stuff
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
import numpy as np
from vines.geometry.geometry import shape
from vines.fields.plane_wave import PlaneWave
from vines.operators.acoustic_operators import volume_potential
from vines.precondition.threeD import circulant_embed_fftw
from vines.operators.acoustic_matvecs import mvp_vec_fftw, mvp_domain
from scipy.sparse.linalg import LinearOperator, gmres
from vines.mie_series_function import mie_function
from matplotlib import pyplot as plt
import time

'''                         Define parameters                               '''
# We consider the field generated by the Sonic Concepts H101 transducer:
# https://sonicconcepts.com/transducer-selection-guide/
# This transducer operates at 1.1 MHz, has a 63.2 mm radius of curvature and a 
# diameter of 64 mm. It has no central aperture.
#
frequency = 1.1e6
# * Sphere info
geom = 'sphere'
radius = 1e-3
refInd = 1.2 + 1j * 0.0
# * Wavelength
lambda_ext = 5e-4
# * Plane wave info
Ao = 1
direction = np.array((1, 0, 0))
ko = 2 * np.pi / lambda_ext  # exterior wavenumber