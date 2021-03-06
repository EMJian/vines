#
# Nonlinear field generated in by a bowl-shaped HIFU transducer
# Convergence of next harmonic as integration domain is increased
# ==========================================================
#
# This demo illustrates how to:
#
# * Compute the nonlinear time-harmonic field in a homogeneous medium
# * Use incident field routines to generate the field from a HIFU transducer
# * Make a nice plot of the solution in the domain
#
#
# We consider the field generated by the Sonic Concepts H101 transducer:
# https://sonicconcepts.com/transducer-selection-guide/
# This transducer operates at 1.1 MHz, has a 63.2 mm radius of curvature and a 
# diameter of 64 mm. It has no central aperture.
# The medium of propagation we consider is water.

import os
import sys
# FIXME: figure out how to avoid this sys.path stuff
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
import numpy as np
from vines.geometry.geometry import shape
from vines.fields.plane_wave import PlaneWave
from vines.operators.acoustic_operators import volume_potential
from vines.precondition.threeD import circulant_embed_fftw
from vines.operators.acoustic_matvecs import mvp_volume_potential, mvp_vec_fftw
from scipy.sparse.linalg import LinearOperator, gmres
from vines.mie_series_function import mie_function
from matplotlib import pyplot as plt
from vines.geometry.geometry import generatedomain
from vines.fields.transducers import bowl_transducer, normalise_power
import time
import matplotlib
from matplotlib import pyplot as plt
import itertools

'''                        Define medium parameters                         '''
# * speed of sound (c)
# * medium density (\rho)
# * the attenuation power law info (\alpha_0, \eta)
# * nonlinearity parameter (\beta)
material = 'water'
c = 1480.0
rho = 1000.0
alpha0 = 0.2
eta = 2
beta = 3.5e0

# material = 'liver'
# c = 1590.0
# rho = 1060
# alpha0 = 90.0
# eta = 1.1
# beta = 4.4


def attenuation(f, alpha0, eta):
    'Attenuation function'
    alpha = alpha0 * (f * 1e-6)**eta
    alpha = alpha / 8.686  # convert to Nepers/m
    return alpha


'''                      Define transducer parameters                       '''
# * operating/fundamental frequency f1
# * radius of curvature, focal length (roc)
# * inner diameter (inner_D)
# * outer diameter (outer_D)
# * total acoustic power (power)
# f1 = 1.1e6
# transducername = 'H131'
# roc = 0.035
# inner_D = 0.0
# outer_D = 0.033
# power = 150

f1 = 1.1e6
transducername = 'H101'
roc = 0.0632
inner_D = 0.0
outer_D = 0.064
power = 100

# FIXME: don't need to define focus location but perhaps handy for clarity?
focus = [roc, 0., 0.]
# FIXME: need source pressure as input

# How many harmonics to compute
# (mesh resolution should be adjusted accordingly, I recommend setting
# nPerLam  >= 3 * n_harm, depending on desired speed and/or accuracy)
n_harm = 5

# Mesh resolution (number of voxels per fundamental wavelength)
nPerLam = 10

# Compute useful quantities: wavelength (lam), wavenumber (k0),
# angular frequency (omega)
lam = c / f1
k1 = 2 * np.pi * f1 / c + 1j * attenuation(f1, alpha0, eta)
omega = 2 * np.pi * f1

# Create voxel mesh
dx = lam / nPerLam

# Dimension of computation domain
# x_start needs to be close to the transducer
# x_end can be just beyond the focus
# the width in the y,z directions should be around the width of outer_D,
# but you can shrink this to speed up computations if required
# x_start = 0.001
x_start = roc - 0.99 * np.sqrt(roc**2 - (outer_D/2)**2)
x_end = roc + 0.01
wx = x_end - x_start
wy = outer_D * 1.0
wz = wy

start = time.time()
r, L, M, N = generatedomain(dx, wx, wy, wz)
# Adjust r
r[:, :, :, 0] = r[:, :, :, 0] - r[0, 0, 0, 0] + x_start
end = time.time()
print('Mesh generation time:', end-start)
points = r.reshape(L*M*N, 3, order='F')

print('Number of voxels = ', L*M*N)

start = time.time()
n_elements = 2**12
x, y, z, p = bowl_transducer(k1, roc, focus, outer_D / 2, n_elements,
                             inner_D / 2, points.T, 'x')
end = time.time()
print('Incident field evaluation time (s):', end-start)
dist_from_focus = np.sqrt((points[:, 0]-focus[0])**2 + points[:, 1]**2 +
                           points[:,2]**2)
idx_near = np.abs(dist_from_focus - roc) < 5e-4
p[idx_near] = 0.0

# Normalise incident field to achieve desired total acoutic power
p0 = normalise_power(power, rho, c, outer_D/2, k1, roc,
                     focus, n_elements, inner_D/2)

p *= p0

P = np.zeros((n_harm, L, M, N), dtype=np.complex128)
P[0] = p.reshape(L, M, N, order='F')

# Create a pretty plot of the first harmonic in the domain
matplotlib.rcParams.update({'font.size': 22})
plt.rc('font', family='serif')
# plt.rc('text', usetex=True)
xmin, xmax = r[0, 0, 0, 0] * 100, r[-1, 0, 0, 0] * 100
ymin, ymax = r[0, 0, 0, 1] * 100, r[0, -1, 0, 1] * 100
fig = plt.figure(figsize=(10, 10))
ax = fig.gca()
plt.imshow(np.abs(P[0, :, :, np.int(np.floor(N/2))].T / 1e6),
           extent=[xmin, xmax, ymin, ymax],
           cmap=plt.cm.get_cmap('viridis'), interpolation='spline16')
plt.xlabel(r'$x$ (cm)')
plt.ylabel(r'$y$ (cm)')
cbar = plt.colorbar()
cbar.ax.set_ylabel('Pressure (MPa)')
filename = 'results/' + transducername + '_power' + str(power) + '_nPerLam' + str(nPerLam) + '.png'
fig.savefig('filename')
plt.close()


def restrict_domain(f_rhs, tol, r):
    import numpy as np
    L, M, N, _ = r.shape
    rel_p = np.abs(f_rhs)/np.max(np.abs(f_rhs))
    where_bigger = np.argwhere(rel_p > tol)
    min_x_idx = np.min(where_bigger[:, 0])
    max_x_idx = np.max(where_bigger[:, 0])
    min_y_idx = np.min(where_bigger[:, 1])
    max_y_idx = np.max(where_bigger[:, 1])
    min_z_idx = np.min(where_bigger[:, 2])
    max_z_idx = np.max(where_bigger[:, 2])

    xMin = r[min_x_idx, 0, 0, 0]
    xMax = r[max_x_idx, 0, 0, 0]
    yMin = r[0, min_y_idx, 0, 1]
    yMax = r[0, max_y_idx, 0, 1]

    # print('Size x = ', (max_x_idx-min_x_idx)*dx)
    # print('Size y,z = ', (max_y_idx-min_y_idx)*dx)

    P_trim = np.zeros((L, M, N), dtype=np.complex128)
    P_trim[min_x_idx:max_x_idx, min_y_idx:max_y_idx, min_z_idx:max_z_idx] = \
        f_rhs[min_x_idx:max_x_idx, min_y_idx:max_y_idx, min_z_idx:max_z_idx]

    return xMin, xMax, yMin, yMax, P_trim


def convergence_domain_size(f_rhs, mvp, circ_op, r, L, M, N, harm, roc, k1):
    TOL = 10**np.array([-0.5, -0.75, -1, -1.25, -1.5, -1.75, -2, -2.25, -2.5,
                        -2.75, -3, -3.25, -3.5, -3.75, -4])
    line_harmonic = np.zeros((TOL.shape[0], L), dtype=np.complex128)
    xMinVals = np.zeros(TOL.shape[0])
    xMaxVals = np.zeros(TOL.shape[0])
    yMinVals = np.zeros(TOL.shape[0])
    yMaxVals = np.zeros(TOL.shape[0])

    for i_tol in range(TOL.shape[0]):
        tol = TOL[i_tol]
        xMin, xMax, yMin, yMax, P_trim = restrict_domain(f_rhs, tol, r)
        xMinVals[i_tol] = xMin
        xMaxVals[i_tol] = xMax
        yMinVals[i_tol] = yMin
        yMaxVals[i_tol] = yMax

        xInVec = P_trim.reshape((L*M*N, 1), order='F')
        start = time.time()
        xOut = mvp(xInVec)
        end = time.time()
        print('Time for MVP:', end-start)
        field = xOut.reshape(L, M, N, order='F')
        ny_centre = np.int(np.floor(M / 2))
        nz_centre = np.int(np.floor(N / 2))
        line = field[:, ny_centre, nz_centre]
        line_harmonic[i_tol, :] = line

    import pickle
    filename = 'results/' + transducername + '_power' + str(power) + \
        '_' + material + '_harmonic' + str(harm) + '_nPerLam' + str(nPerLam) + '.pickle'
    with open(filename, 'wb') as f:
        pickle.dump([line_harmonic, TOL, xMinVals, xMaxVals, yMinVals,
                     yMaxVals, roc, np.real(k1)], f)
    return xMinVals


'''      Compute the next harmonics by evaluating the volume potential      '''
for i_harm in range(1, n_harm):
    f2 = (i_harm + 1) * f1
    k2 = 2 * np.pi * f2 / c + 1j * attenuation(f2, alpha0, eta)

    # Assemble volume potential Toeplitz operator perform circulant embedding
    start = time.time()
    toep_op = volume_potential(k2, r)

    circ_op = circulant_embed_fftw(toep_op, L, M, N)
    end = time.time()
    print('Operator assembly and its circulant embedding:', end-start)

    # Create vector for matrix-vector product
    if i_harm == 1:
        # Second harmonic
        xIn = -2 * beta * omega**2 / (rho * c**4) * P[0] * P[0]
    elif i_harm == 2:
        # Third harmonic
        xIn = -9 * beta * omega**2 / (rho * c**4) * P[0] * P[1]
    elif i_harm == 3:
        # Fourth harmonic
        xIn = -8 * beta * omega**2 / (rho * c**4) * \
            (P[1] * P[1] + 2 * P[0] * P[2])
    elif i_harm == 4:
        # Fifth harmonic
        xIn = -25 * beta * omega**2 / (rho * c**4) * \
            (P[0] * P[3] + P[1] * P[2])

    xInVec = xIn.reshape((L*M*N, 1), order='F')
    idx = np.ones((L, M, N), dtype=bool)

    # Voxel permittivities
    Mr = np.ones((L, M, N), dtype=np.complex128)

    def mvp(x):
        'Matrix-vector product operator'
        return mvp_volume_potential(x, circ_op, idx, Mr)

    xMinVals = convergence_domain_size(xIn, mvp, circ_op, r, L, M, N,
                                       i_harm+1, roc, k1)

    # Perform matrix-vector product
    start = time.time()
    P[i_harm] = mvp(xInVec).reshape(L, M, N, order='F')
    end = time.time()
    print('MVP time = ', end - start)

# Plot harmonics along central axis
ny_centre = np.int(np.floor(M/2))
nz_centre = np.int(np.floor(N/2))
x_line = (r[:, ny_centre, nz_centre, 0]) * 100
fig = plt.figure(figsize=(14, 8))
ax = fig.gca()
marker = itertools.cycle(('k-', 'r-', 'b-', 'g-', 'y-'))
for i in range(0, n_harm):
    plt.plot(x_line, np.abs(P[i, :, ny_centre, nz_centre])/1e6, next(marker))
plt.grid(True)
plt.xlim([x_start*100, x_end*100])
plt.ylim([0, np.ceil(np.max(np.abs(P[0, :, ny_centre, nz_centre])/1e6))])
plt.xlabel(r'Axial distance (cm)')
plt.ylabel(r'Pressure (MPa)')
# filename = 'results/' + transducername + '_power' + str(power) + \
#         '_water_harms_axis.pdf'
filename = 'results/' + transducername + '_power' + str(power) + \
        '_' + material + '_harms_axis' + '_nPerLam' + str(nPerLam) + '.pdf'      
fig.savefig(filename)
plt.close()


# Save first harmonic along central axis
import pickle
# filename = 'results/' + transducername + '_power' + str(power) + \
#         '_water_harmonic1' + '.pickle'
filename = 'results/' + transducername + '_power' + str(power) + \
        '_' + material + '_harmonic1' + '_nPerLam' + str(nPerLam) + '.pickle'
with open(filename, 'wb') as f:
    pickle.dump([P[0, :, ny_centre, nz_centre], x_line], f)
