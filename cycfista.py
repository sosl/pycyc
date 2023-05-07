#!/usr/bin/env python
# coding: utf-8

import numpy as np
import pycyc
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import matplotlib as mpl
from plotting import plot_intrinsic_vs_observed
import copy
import pickle
import importlib
import sys
import time

mpl.rcParams["image.aspect"] = "auto"
from scipy.fft import rfft, fft, fftshift, ifft, fftn, ifftn

CS = pycyc.CyclicSolver("P2067/chan07/53873.27864.07.15s.t2", zap_edges = 0.05556, pscrunch=True)
CS.data.shape, CS.nspec

CS.load("P2067/chan07/53873.31676.07.15s.t2")
CS.data.shape, CS.nspec

CS.save_cyclic_spectra = True
CS.iprint = False
CS.initProfile()

plt.plot(CS.pp_int)
plt.savefig('cycfista_init_profile.png')

pp_scattered = np.copy(CS.pp_ref)

CS.iprint = False
CS.make_plots = False
CS.ml_profile = False
CS.enforce_orthogonal_real_imag = False

CS.niter = 0
CS.initWavefield()

y_n = np.copy(CS.h_doppler_delay)
x_n = np.copy(CS.h_doppler_delay)
t_n = 1

CS.iprint = 0
demerits = np.array([])
alpha = 20.0

best_merit = CS.merit
best_x = np.copy(x_n)
L_max = 1.0 / alpha

print(f"starting merit={best_merit}")

step_factor=1.0
acceleration=2.0
bad_step = 0

prev_merit = best_merit

# Start timer
start_time = time.time()
min_step_factor = 0.1

for i in range (1000):
    
    CS.nopt += 1
            
    x_n, y_n, L, t_n, demerits = fista.take_fista_step(iter=i, func=CS, 
        backtrack=False, alpha=alpha, 
        eta=5, y_n=y_n, _lambda=None,
        delay_for_inf=-int(CS.nchan/2), 
        zero_penalty_coords = np.array([]),
        fix_phase_value = None,
        fix_phase_coords = None,
        fix_support= np.array([]),
        t_n=t_n,
        x_n=x_n,
        demerits = demerits,
        eps = None,
    )

    if L > L_max:
      L_max = L

    if CS.merit < best_merit:
        best_merit = CS.merit
        best_x = np.copy(x_n)
    else:
        print (f"\n** greater than best={best_merit}")

    if CS.merit > prev_merit:
        print ("**** bad step")
        reset = False
        if reset:
            if step_factor < min_step_factor:
                print ("****** reset")
                x_n = np.copy(best_x)
                y_n = np.copy(best_x)
                t_n = 1
                step_factor = min_step_factor
            else:
                step_factor /= acceleration
    else:
        step_factor = np.tanh( step_factor * acceleration )

    alpha = step_factor / L_max
    prev_merit = CS.merit
    
    print(f"\ndemerit={CS.merit} alpha={alpha} step_factor={step_factor} t_n={t_n}")
    end_time = time.time()

    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time/60} min") 

    if i % 10 == 0:
        base = 'cycfista_' + str(i)
        plotthis = np.log10(np.abs(fftshift(x_n))+ 1e-2)
        plt.imshow(plotthis.T, aspect="auto", origin="lower", cmap="cubehelix_r", vmin=-1)
        plt.colorbar()
        plt.savefig(base + '_wavefield.png')
        plot_intrinsic_vs_observed(CS, pp_scattered, base + '_compare.png')

