#
# Nonlinear field scattered by a homogeneous sphere
# =================================================
#
# This demo illustrates how to:
#
# * Compute the scattering of a nonlinear time-harmonic field by an obstacle
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
from vines.operators.acoustic_matvecs import mvp_volume_potential, mvp_vec_fftw, mvp_potential_x_perm
from scipy.sparse.linalg import LinearOperator, gmres
from vines.mie_series_function import mie_function
from matplotlib import pyplot as plt
from vines.geometry.geometry import generatedomain, grid3d
from vines.fields.transducers import bowl_transducer, normalise_power
from vie_solve import vie_solver
import time
import matplotlib
from matplotlib import pyplot as plt

'''                        Define medium parameters                         '''
# * speed of sound (c)
# * medium density (\rho)
# * the attenuation power law info (\alpha_0, \eta)
# * nonlinearity parameter (\beta)
c = 1487.0
rho = 998.0
alpha0 = 0.217
eta = 2
beta = 3.5e0


def attenuation(f, alpha0, eta):
    'Attenuation function'
    alpha = alpha0 * (f * 1e-6)**eta
    return alpha


'''                      Define transducer parameters                       '''
# * operating/fundamental frequency f1
# * radius of curvature / focal length (roc)
# * inner diameter (inner_D)
# * outer diameter (outer_D)
# * total acoustic power (power)
f1 = 1.1e6
roc = 0.0632
inner_D = 0.0
outer_D = 0.064
power = 44
# FIXME: don't need to define focus location but perhaps handy for clarity?
focus = [roc, 0., 0.]
# FIXME: need source pressure as input

'''                            Define scatterer                             '''
# Define a 1mm radius sphere halfway between transducer and focus
geom = 'sphere'
radius = 10e-3
refInd = 1.07 + 1j * 0.0  # defined as k_int / k_ext FIXME:CHECK
location = [roc - 0.02, 0., 0.]  # centre of scatterer

# Compute useful quantities: wavelength (lam), wavenumber (k0),
# angular frequency (omega)
lam = c / f1
k1 = 2 * np.pi * f1 / c + 1j * attenuation(f1, alpha0, eta)
omega = 2 * np.pi * f1

# Mesh resolution (number of voxels per fundamental wavelength)
nPerLam = 6

# Create voxel mesh
dx = lam / nPerLam

# Dimension of computation domain
x_start = 0.01
x_end = roc + 0.01
wx = x_end - x_start
wy = outer_D / 4
wz = wy
# embed()

start = time.time()
r, L, M, N = generatedomain(dx, wx, wy, wz)
# Adjust r
r[:, :, :, 0] = r[:, :, :, 0] - r[0, 0, 0, 0] + x_start
end = time.time()
print('Mesh generation time:', end-start)
# embed()
points = r.reshape(L*M*N, 3, order='F')

print('Number of voxels = ', L*M*N)

# Generate incident field
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

n_harm = 2
P = np.zeros((n_harm, L, M, N), dtype=np.complex128)
P_sca = np.zeros((n_harm, L, M, N), dtype=np.complex128)
P_inc = np.zeros((n_harm, L, M, N), dtype=np.complex128)
P_inc[0] = p.reshape(L, M, N, order='F')

'''                    Compute scattering (first harmonic)                  '''
# First locate the portion of mesh inside the scatterer
r_sq = (r[:, :, :, 0] - location[0])**2 + (r[:, :, :, 1] - location[1])**2 + \
    (r[:, :, :, 2] - location[2])**2
idx_scat = (r_sq <= radius**2)

xd, yd, zd = r[:, :, :, 0], r[:, :, :, 1], r[:, :, :, 2]
# Find indices of bounding box of scatterer
idx_box = (xd <= max(xd[idx_scat]) + 1e-6) * \
          (xd >= min(xd[idx_scat]) - 1e-6) * \
          (yd <= max(yd[idx_scat]) + 1e-6) * \
          (yd >= min(yd[idx_scat]) - 1e-6) * \
          (zd <= max(zd[idx_scat]) + 1e-6) * \
          (zd >= min(zd[idx_scat]) - 1e-6)

x_box = np.arange(min(xd[idx_scat]), max(xd[idx_scat]) + 1e-6, dx)
y_box = np.arange(min(yd[idx_scat]), max(yd[idx_scat]) + 1e-6, dx)
z_box = np.arange(min(zd[idx_scat]), max(zd[idx_scat]) + 1e-6, dx)

r_box, L_box, M_box, N_box = grid3d(x_box, y_box, z_box)

r_sq_box = (r_box[:, :, :, 0] - location[0])**2 + \
    (r_box[:, :, :, 1] - location[1])**2 + \
    (r_box[:, :, :, 2] - location[2])**2
idx_scat_box = (r_sq_box <= radius**2)

# Voxel permittivities
Mr_box = np.zeros((L_box, M_box, N_box), dtype=np.complex128)
Mr_box[idx_scat_box] = refInd**2 - 1

'''         Solve scattering problem only over inhomogeneous region         '''
# FIXME: come up with a better name for J
sol, J, u_sca = vie_solver(Mr_box, r_box, idx_scat_box, P_inc[0][idx_scat], k1)

'''          Evaluate total field over total domain (u_inc + u_sca)         '''
# Toeplitz operator
T = k1**2 * volume_potential(k1, r)

# Circulant embedding of Toeplitz operator
circ = circulant_embed_fftw(T, L, M, N)

# Voxel permittivities
Mr = np.zeros((L, M, N), dtype=np.complex128)
Mr[idx_scat] = refInd**2 - 1
# Mr[idx_box] = Mr_box.reshape((L_box*M_box*N_box, 1), order='F')[:, 0]

J_domain = np.zeros((L, M, N), dtype=np.complex128)
J_domain[idx_box] = J.reshape((L_box*M_box*N_box, 1))[:, 0]

# Evaluate at all voxels
idx_all = np.ones((L, M, N), dtype=bool)

P_sca[0] = mvp_potential_x_perm(J_domain.reshape((L*M*N, 1), order='F'),
                                circ, idx_all, Mr).reshape(L, M, N, order='F')

P[0] = P_inc[0] + P_sca[0]


ny_centre = np.int(np.floor(M/2))
nz_centre = np.int(np.floor(N/2))
# x_line = (r[:, ny_centre, nz_centre, 0]) * 100
# plt.plot(x_line, np.abs(P1[:, ny_centre, nz_centre])/1e6,'k-', linewidth=2)
# plt.show()

'''      Compute the next harmonics by evaluating the volume potential      '''
n_harm = 2
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
    idx_all = np.ones((L, M, N), dtype=bool)

    # def mvp(x):
    #     'Matrix-vector product operator'
    #     return mvp_volume_potential(x, circ_op, idx, Mr)

    # Voxel permittivities for volume potential (all ones)
    Mr_vol_pot = np.ones((L, M, N), dtype=np.complex128)

    # Perform matrix-vector product
    start = time.time()
    # P_inc[i_harm] = mvp(xInVec).reshape(L, M, N, order='F')
    P_inc[i_harm] = mvp_volume_potential(xInVec, circ_op, idx_all, Mr_vol_pot).reshape(L, M, N, order='F')

    # from IPython import embed; embed()

    # Solve scattering problem
    sol, J, u_sca = vie_solver(Mr_box, r_box, idx_scat_box,
                               P_inc[i_harm][idx_scat], k2)

    # Evaluate scattered field in total domain
    # Toeplitz operator
    T = k2**2 * volume_potential(k2, r)

    # Circulant embedding of Toeplitz operator
    circ = circulant_embed_fftw(T, L, M, N)

    J_domain = np.zeros((L, M, N), dtype=np.complex128)
    J_domain[idx_box] = J.reshape((L_box*M_box*N_box, 1))[:, 0]

    P_sca[i_harm] = mvp_potential_x_perm(J_domain.reshape((L*M*N, 1), order='F'),
                                    circ, idx_all, Mr).reshape(L, M, N, order='F')

    P[i_harm] = P_inc[i_harm] + P_sca[i_harm]



# Plot harmonics along central axis
matplotlib.rcParams.update({'font.size': 22})
plt.rc('font', family='serif')
plt.rc('text', usetex=True)
x_line = (r[:, ny_centre, nz_centre, 0]) * 100
fig = plt.figure(figsize=(14, 8))
ax = fig.gca()
plt.plot(x_line, np.abs(P[0, :, ny_centre, nz_centre])/1e6, 'k-')
plt.plot(x_line, np.abs(P[1, :, ny_centre, nz_centre])/1e6, 'r-')
plt.grid(True)
plt.xlim([x_start*100, x_end*100])
plt.ylim([0, np.ceil(np.max(np.abs(P[0, :, ny_centre, nz_centre])/1e6))])
plt.xlabel(r'Axial distance (cm)')
plt.ylabel(r'Pressure (MPa)')
fig.savefig('results/H101_harms_axis_scatter.pdf')
plt.close()



# Create a pretty plot of the first harmonic in the domain
# matplotlib.use('Agg')
xmin, xmax = r[0, 0, 0, 0] * 100, r[-1, 0, 0, 0] * 100
ymin, ymax = r[0, 0, 0, 1] * 100, r[0, -1, 0, 1] * 100
fig = plt.figure(figsize=(10, 10))
ax = fig.gca()
plt.imshow(np.abs(P[0][:, :, np.int(np.floor(N/2))].T),
           extent=[xmin, xmax, ymin, ymax],
           cmap=plt.cm.get_cmap('viridis'))#, interpolation='spline16')
plt.xlabel(r'$x$ (cm)')
plt.ylabel(r'$y$ (cm)')
cbar = plt.colorbar()
cbar.ax.set_ylabel('Pressure (MPa)')
fig.savefig('results/H101_scatter.png')
plt.close()