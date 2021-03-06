#
# Nonlinear field generated in by a bowl-shaped HIFU transducer
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
from vines.operators.acoustic_operators import volume_potential, volume_potential_cylindrical
from vines.precondition.threeD import circulant_embed_fftw
from vines.operators.acoustic_matvecs import mvp_volume_potential, mvp_vec_fftw
from scipy.sparse.linalg import LinearOperator, gmres
from vines.mie_series_function import mie_function
from matplotlib import pyplot as plt
from vines.geometry.geometry import generatedomain2d, generatedomain
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
# c = 1487.0
# rho = 998.0
# alpha0 = 0.217
# eta = 2
# beta = 3.5e0

material = 'liver'
c = 1590.0
rho = 1040
alpha0 = 90.0
eta = 1.1
beta = 4.4


def attenuation(f, alpha0, eta):
    'Attenuation function'
    alpha = alpha0 * (f * 1e-6)**eta
    alpha = alpha / 8.686
    return alpha


'''                      Define transducer parameters                       '''
# * operating/fundamental frequency f1
# * radius of curvature, focal length (roc)
# * inner diameter (inner_D)
# * outer diameter (outer_D)
# * total acoustic power (power)
# f1 = 1.1e6
# roc = 0.0632
# inner_D = 0.0
# outer_D = 0.064
# power = 50

f1 = 1.1e6
transducername = 'H131'
roc = 0.035
inner_D = 0.0
outer_D = 0.033
power = 100


# FIXME: don't need to define focus location but perhaps handy for clarity?
focus = [roc, 0., 0.]
# FIXME: need source pressure as input

# How many harmonics to compute
# (mesh resolution should be adjusted accordingly, I recommend setting
# nPerLam  >= 3 * n_harm, depending on desired speed and/or accuracy)
n_harm = 2

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
# x_start = roc - 0.99 * np.sqrt(roc**2 - (outer_D/2)**2)
x_start = 0
x_end = roc + 0.01
wx = x_end - x_start
wy = outer_D*1
wz = wy/1000
# wz = wy

start = time.time()
# r, L, M = generatedomain2d(dx, wx, wy)
r, L, M, N = generatedomain(dx, wx, wy, wz)

# Adjust r by shifting x locations
r[:, :, :, 0] = r[:, :, :, 0] - r[0, 0, 0, 0] + x_start
# r[:, :, :, 1] = r[:, :, :, 1] - r[0, 0, 0, 1]
end = time.time()
print('Mesh generation time:', end-start)
points = r.reshape(L*M*N, 3, order='F')

# from IPython import embed; embed()


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
plt.rc('text', usetex=True)
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
fig.savefig('results/test.png')
plt.close()

from IPython import embed; embed()
exit()

'''      Compute the next harmonics by evaluating the volume potential      '''
for i_harm in range(1, n_harm):
    f2 = (i_harm + 1) * f1
    k2 = 2 * np.pi * f2 / c + 1j * attenuation(f2, alpha0, eta)

    # Assemble volume potential Toeplitz operator perform circulant embedding
    start = time.time()
    toep_op = volume_potential_cylindrical(k2, r)

    circ_op = circulant_embed_fftw(toep_op, L, M, N)
    end = time.time()
    print('Operator assembly and its circulant embedding:', end-start)

    # Create vector for matrix-vector product
    if i_harm == 1:
        # Second harmonic
        xIn = -2 * beta * omega**2 / (rho * c**4) * P[0] * P[0] * np.abs(r[:, :, :, 1])# * 2 * np.pi
    elif i_harm == 2:
        # Third harmonic
        xIn = -9 * beta * omega**2 / (rho * c**4) * P[0] * P[1]* np.abs(r[:, :, :, 1]) #* np.pi
    elif i_harm == 3:
        # Fourth harmonic
        xIn = -8 * beta * omega**2 / (rho * c**4) * \
            (P[1] * P[1] + 2 * P[0] * P[2])* np.abs(r[:, :, :, 1]) * np.pi
    elif i_harm == 4:
        # Fifth harmonic
        xIn = -25 * beta * omega**2 / (rho * c**4) * \
            (P[0] * P[3] + P[1] * P[2])* np.abs(r[:, :, :, 1]) * np.pi
    elif i_harm == 5:
        # Sixth harmonic
        xIn = -18 * beta * omega**2 / (rho * c**4) * \
            (2 * P[0] * P[4] + 2 * P[1] * P[3] + P[2]**2)* np.abs(r[:, :, :, 1]) * np.pi
    elif i_harm == 6:
        # Seventh harmonic
        xIn = -49 * beta * omega**2 / (rho * c**4) * \
            (P[0] * P[5] + P[1] * P[4] + P[2] * P[3])* np.abs(r[:, :, :, 1]) * np.pi

    xInVec = xIn.reshape((L*M*N, 1), order='F')
    idx = np.ones((L, M, N), dtype=bool)

    def mvp(x):
        'Matrix-vector product operator'
        return mvp_volume_potential(x, circ_op, idx, Mr)

    # Voxel permittivities
    Mr = np.ones((L, M, N), dtype=np.complex128)

    # Perform matrix-vector product
    start = time.time()
    P[i_harm] = mvp(xInVec).reshape(L, M, N, order='F')
    end = time.time()
    print('MVP time = ', end - start)

# f2 = 2 * f1
# k2 = 2 * np.pi * f2 / c + 1j * attenuation(f2, alpha0, eta)

# # Assemble volume potential Toeplitz operator perform circulant embedding
# start = time.time()
# toep_op = volume_potential_cylindrical(k2, r)
# # toep_op = volume_potential(k2, r)

# circ_op = circulant_embed_fftw(toep_op, L, M, N)
# end = time.time()
# print('Operator assembly and its circulant embedding:', end-start)

# # Second harmonic
# # xIn = -2 * beta * omega**2 / (rho * c**4) * P * P

# xIn = -2 * beta * omega**2 / (rho * c**4) * P[0] * P[0] * np.abs(r[:, :, :, 1]) * np.pi


# xInVec = xIn.reshape((L*M*N, 1), order='F')
# idx = np.ones((L, M, N), dtype=bool)

# def mvp(x):
#     'Matrix-vector product operator'
#     return mvp_volume_potential(x, circ_op, idx, Mr)

# # Voxel permittivities
# Mr = np.ones((L, M, N), dtype=np.complex128)

# # Perform matrix-vector product
# start = time.time()
# P[1] = mvp(xInVec).reshape(L, M, N, order='F')
# end = time.time()
# print('MVP time = ', end - start)
# from IPython import embed; embed()


# Now evaluate the volume potential for points along central axis
dA = dx**2  # element of area
# Central axis line
x_line = r[:, 0, 0, :] - np.array([0, dx/2, 0])

# k2 = k1 * 2

# integral = np.zeros(L, dtype=np.complex128)
# for i in range(L):
#     R0 = x_line[i, :]
#     ri_to_rk = r[:, :, 0, :] - R0
#     dist = np.linalg.norm(ri_to_rk) 
#     dist = np.sqrt(ri_to_rk[:,:,0]**2 + ri_to_rk[:,:,1]**2 + ri_to_rk[:,:,2]**2)
#     integrand = np.exp(1j * k2 * dist) / (4 * np.pi * dist) * \
#                 r[:, :, 0, 1] * P[:, :, 0]**2
#     integral[i] = -2 * beta * omega**2 / (rho * c**4) * 2 * np.pi * \
#                 np.sum(integrand) * dA



# Create a pretty plot of the first harmonic in the domain
matplotlib.rcParams.update({'font.size': 22})
plt.rc('font', family='serif')
plt.rc('text', usetex=True)
xmin, xmax = r[0, 0, 0, 0] * 100, r[-1, 0, 0, 0] * 100
ymin, ymax = r[0, 0, 0, 1] * 100, r[0, -1, 0, 1] * 100
fig = plt.figure(figsize=(10, 10))
ax = fig.gca()
plt.imshow(np.abs(P[1, :, :, np.int(np.floor(N/2))].T / 1e6),
           extent=[xmin, xmax, ymin, ymax],
           cmap=plt.cm.get_cmap('viridis'), interpolation='spline16')
plt.xlabel(r'$x$ (cm)')
plt.ylabel(r'$y$ (cm)')
cbar = plt.colorbar()
cbar.ax.set_ylabel('Pressure (MPa)')
fig.savefig('results/test1.png')
plt.close()

# marker = itertools.cycle(('ko-', 'rs-', 'd-', 'x-', '*-', '+-'))
ny_centre = np.int(np.floor(M/2))
nz_centre = np.int(np.floor(N/2))
x_line = (r[:, ny_centre, nz_centre, 0]) * 100
fig = plt.figure(figsize=(14, 8))
ax = fig.gca()
for i_harm in range(n_harm):
    # plt.plot(x_line, np.abs(P[i_harm, :, ny_centre, nz_centre])/1e6)
    plt.plot(x_line, np.abs(P[i_harm, :, 0, 0])/1e6)
# plt.plot(x_line, np.abs(P1[:, ny_centre, nz_centre])/1e6, 'r-')
plt.grid(True)
plt.xlim([x_start*100, x_end*100])
plt.ylim([0, 8])
plt.xlabel(r'Axial distance (cm)')
plt.ylabel(r'Pressure (MPa)')
fig.savefig('results/test2.png')
plt.close()


