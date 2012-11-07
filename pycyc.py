"""
pycyc - python implementation of Cyclic-Modelling https://github.com/demorest/Cyclic-Modelling
Glenn Jones

This is designed to be a library of python functions to be used interactively with ipython
or in other python scripts. However, for demonstration purposes you can run this as a stand-alone script:

python2.7 pycyc.py input_cs_file.ar   # This will generate an initial profile from the data itself

python2.7 pycyc.py input_cs_file.ar some_profile.txt  # This will use the profile in some_profile.txt

The majority of these routines have been checked against the original Cyclic-Modelling code
and produce identical results to floating point accuracy. The results of the optimization may
not be quite as identical since Cyclic-Modelling uses the nlopt implementation of the L_BFGS solver
while this code uses scipy.optimize.fmin_l_bfgs_b

Here's an example of how I use this on kermit.

$ ipython -pylab

import pycyc

CS = pycyc.CyclicSolver(filename='/psr/gjones/2011-09-19-21:50:00.ar') # some 1713 data  at 430 MHz Nipuni processed

CS.initProfile(loadFile='/psr/gjones/pp_1713.npy') # start with a nice precomputed profile.
# Note profile can be in .txt (filter_profile) format or .npy numpy.save format.

# have a look at the profile:
plot(CS.pp_int)

CS.data.shape
Out: (1, 2, 256, 512)  # 1 subintegration, 2 polarizations, 256 freq channels, 512 phase bins

CS.loop(isub = 0, make_plots=True,ipol=0,tolfact=20) # run the optimzation
# Note this does the "inner loop": sets up the non-linear optimization and runs it
# the next step will be to build the "outer loop" which uses the new guess at the intrinsic profile
# to reoptimize the IRF. This isn't yet implemented but the machinary is all there.
#
# Running this with make_plots will create a <filename>_plots subdirectory with plots of various
# data products. The plots are made each time the objective function is evaluated. Note that there
# can be more than one objective function evaluation per solver iteration.
#
# tolfact can be used to reduce the stringency of the stopping criterion. This seems to be particularly useful
# to avoid overfitting to the noise in real data

# after the optimization runs, have a look at the CS data
clf()
imshow((np.abs(CS.cs))[:,1:],aspect='auto')

# have a look at the IRF
ht = pycyc.freq2time(CS.hf_prev)
t = np.arange(ht.shape[0]) / CS.bw # this will be time in microseconds since CS.bw is in MHz
subplot(211)
plot(t,abs(ht))

# compute the model CS and have a look

csm = CS.modelCS(ht)
subplot(212)
imshow(np.log10(np.abs(csm)),aspect='auto')
colorbar()

# Now examine the effect of zeroing the "noisy" parts of the IRF

ht2 = ht[:] #copy ht
ht2[:114] = 0
ht2[143:] = 0
csm2 = CS.modelCS(ht2)
figure()
subplot(211)
plot(t,abs(ht2))
subplot(212)
imshow(np.log10(np.abs(csm2)),aspect='auto')
colorbar()


# Try a bounded optimizaton, constraining h(t) to have support over a limited range
# the two parameters are:
# maxneg : int or None
#    The number of samples before the delta function which are allowed to be nonzero
#    This value must be given to turn on bounded optimization
# maxlen : int or None
#    The maximum length of the impulse response in samples

# e.g. suppose we want to limit the IRF to only have support from -1 to +10 us and CS.bw ~ 10 MHz
# maxneg = int(1e-6 * 10e6) = 10
# maxlen = int((1e-6 + 10e-6) * 10e6) = 110

CS.loop(make_plots=True, tolfact=10, maxneg=10, maxlen = 110)

"""
try:
    import psrchive
except:
    print "pycyc.py: psrchive python libraries not found. You will not be able to load psrchive files."
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.figure import Figure                         
from matplotlib.backends.backend_agg import FigureCanvasAgg 
import time
import cPickle
import scipy, scipy.optimize
import os

class CyclicSolver():
    def __init__(self, filename=None, statefile=None, offp = None,tscrunch=None):
        """
        
        *offp* : passed to the load method for selecting an off pulse region (optional).
        *tscrunch* : passed to the load method for averaging subintegrations
        """
        if filename:
            self.load(filename,offp=offp)
        elif statefile:
            self.loadState(statefile)
        else:
            self.ar = None
            
        self.statefile = statefile
        
    def modelCS(self,ht=None,hf=None):
        """
        Convenience function for computing modelCS using ref profile
        
        Call as modelCS(ht) for time domain or modelCS(hf=hf) for freq domain
        """
        if ht is not None:
            hf = time2freq(ht)
        cs,a,b,c = make_model_cs(hf, self.s0, self.bw, self.ref_freq)
        
        return cs
            
    def load(self,filename,offp=None,maxchan = None,tscrunch=None):
        """ 
        Load periodic spectrum from psrchive compatible file (.ar or .fits)
        
        *offp*: tuple (start,end) with start and end bin numbers to use as off pulse region for normalizing the bandpass
        
        *maxchan*: Top channel index to use. Quick and dirty way to pull out one subband from a file which contains multiple
                    subbands
        *tscrunch* : average down by a factor of 1/tscrunch (i.e. if tscrunch = 2, average every pair of subints)
        """
        idx = 0 # only used to get parameters of integration, not data itself
        
        self.filename = filename
        self.ar = psrchive.Archive_load(filename)
        
        self.data = self.ar.get_data()  #we load all data here, so this should probably change in the long run
        if maxchan:
            bwfact = maxchan/(1.0*self.data.shape[2]) # bwfact used to indicate the actual bandwidth of the data if we're not using all channels.
            self.data = self.data[:,:,:maxchan,:]
        else:
            bwfact = 1.0
        if offp:
            self.data = self.data/(np.abs(self.data[:,:,:,offp[0]:offp[1]]).mean(3)[:,:,:,None])
        if tscrunch:
            for k in range(1,tscrunch):
                self.data[:-k,:,:,:] += self.data[k:,:,:,:]
#            d = self.data
#            nsub = d.shape[0]/tscrunch
#            ntot = nsub*tscrunch
#            self.data = d[:ntot,:,:,:].reshape((nsub,tscrunch,d.shape[1],d.shape[2],d.shape[3])).mean(1)
        subint = self.ar.get_Integration(idx)
        self.nspec,self.npol,self.nchan,self.nbin = self.data.shape
        
        epoch = subint.get_epoch()
        try:
            self.imjd = np.floor(epoch)
            self.fmjd = np.fmod(epoch,1)
        except: #new version of psrchive has different kind of epoch
            self.imjd = epoch.intday()
            self.fmjd = epoch.fracday()
        self.ref_phase = 0.0
        self.ref_freq = 1.0/subint.get_folding_period()
        self.bw = np.abs(subint.get_bandwidth()) * bwfact
        self.rf = subint.get_centre_frequency()
        
        self.source = self.ar.get_source() # source name

        self.nlag = self.nchan
        self.nphase = self.nbin
        self.nharm = self.nphase/2 + 1
        
        self.dynamic_spectrum = np.zeros((self.nspec,self.nchan))
        self.optimized_filters = np.zeros((self.nspec,self.nchan),dtype='complex')
        self.intrinsic_profiles = np.zeros((self.nspec,self.nbin))
        self.nopt = 0
        self.nloop = 0        
        
    def initProfile(self,loadFile=None,ipol=0,maxinitharm=None):
        """
        Initialize the reference profile
        
        If loadFile is not specified, will compute an initial profile from the data
        If loadFile ends with .txt, it is assumed to be a filter_profile output file
        If loadFile ends with .npy, it is assumed to be a numpy data file
        
        Resulting profile is assigned to self.pp_ref
        The results of this routine have been checked to agree with filter_profile -i
        
        *maxinitharm* : zero harmonics above this one in the initial profile (acts to smooth/denoise) (optional)
        
        """
        hf_prev = np.ones((self.nchan,),dtype='complex')
        self.hf_prev = hf_prev
        
        self.pp_int = np.zeros((self.nphase)) #intrinsic profile

        if loadFile:
            if loadFile.endswith('.npy'):
                self.pp_ref = np.load(loadFile)
            elif loadFile.endswith('.txt'):
                self.pp_ref = loadProfile(loadFile)
            else:
                raise Exception("Filename must end with .txt or .npy to indicate type")
            return
        
        #initialize profile from data
        #the results of this routine have been checked against filter_profile and they perform the same
        for isub in range(self.data.shape[0]):
            ps = self.data[isub,ipol]
            cs = ps2cs(ps)
            cs = normalize_cs(cs,bw=self.bw,ref_freq=self.ref_freq)
            cs = cyclic_padding(cs,self.bw,self.ref_freq)
            hf = np.ones((self.nchan,),dtype='complex')
            ht = freq2time(hf)
            rindex = np.abs(ht).argmax()
            self.rindex = rindex
                    
            ph = optimize_profile(cs,hf,self.bw,self.ref_freq)
            ph[0] = 0.0
            if maxinitharm:
                ph[maxinitharm:] = 0.0
            pp = harm2phase(ph)
            
            self.pp_int += pp
            
        self.pp_ref = self.pp_int[:]
        
    def solve(self,**kwargs):
        """
        Construct an iterative solution to the IRF using multiple subintegrations
        """
        if kwargs.pop('restart',False):
                self.nopt = 0
        savefile = kwargs.pop('savebase',os.path.abspath(self.filename)+('_%02d.cysolve.pkl' % self.nloop))

        if kwargs.has_key('savedir'):
            savedir = kwargs['savedir']
        for isub in range(self.nspec):
            kwargs['isub'] = isub
            self.loop(**kwargs)
            print "Saving after nopt:", self.nopt
            self.saveState(savefile)
            
        self.pp_ref = self.pp_int
        self.nloop += 1

        
    def loop(self,isub=0,ipol=0,hf_prev=None,make_plots=False,
             maxfun = 1000, tolfact=1, iprint=1, plotdir = None,
             maxneg = None, maxlen = None, rindex= None,
             ht0 = None,max_plot_lag=50,use_last_soln=True, use_minphase = True,
             onp=None,adjust_delay=True):
        """
        Run the non-linear solver to compute the IRF
        
        maxfun: int
            maximum number of objective function evaluations
        tolfact: float
            factor to multiply the convergence limit by. Default 1
            uses convergence criteria from original filter_profile.
            Try 10 for less stringent (faster) convergence
        iprint: int
            Passed to scipy.optimize.fmin_l_bfgs (see docs)
            use 0 for silent, 1 for verbose, 2 for more log info
            
        max_plot_lag: highest lag to plot in diagnostic plots.
        use_last_soln: If true, use last filter as initial guess for this subint
        use_minphase: if true, use minimum phase IRF as initial guess
                        else use delta function
        """
        self.make_plots = make_plots
        if make_plots:
            self.mlag = max_plot_lag
            if plotdir is None:
                blah,fbase = os.path.split(self.filename)
                plotdir = os.path.join(os.path.abspath(os.path.curdir),('%s_plots' % fbase))
            if not os.path.exists(plotdir):
                try:
                    os.mkdir(plotdir)
                except:
                    print "Warning: couldn't make",plotdir,"not plotting"
                    self.make_plots = False
            self.plotdir = plotdir
                
        self.isub = isub
        self.ipol = ipol
        self.iprint = iprint
        ps = self.data[isub,ipol] #dimensions will now be (nchan,nbin)
        cs = ps2cs(ps)
        cs = normalize_cs(cs,bw=self.bw,ref_freq=self.ref_freq)
        cs = cyclic_padding(cs,self.bw,self.ref_freq)
        
        
        if hf_prev is None:
            _hf_prev = self.hf_prev
        else:
            _hf_prev = hf_prev
        
        self.ps = ps
        self.cs = cs
        
        self.dynamic_spectrum[isub,:] = np.real(cs[:,0])
        
        self.ph_ref = phase2harm(self.pp_ref)
        self.ph_ref = normalize_profile(self.ph_ref)
        self.ph_ref[0] = 0
        ph = self.ph_ref[:]
        self.s0 = ph
                    
        if self.nopt == 0 or not use_last_soln:
            self.pp_int = np.zeros((self.nphase,))
            if ht0 is None:
                if rindex is None:
                    delay = self.phase_gradient(cs)
                else:
                    delay = rindex
                print "initial filter: delta function at delay = %d" % delay
                ht = np.zeros((self.nlag,),dtype='complex')
                ht[delay] = self.nlag
                if use_minphase:
                    if onp is None:
                        print "onp not specified, so not using minimum phase"
                    else:
                        spect = np.abs(self.data[isub,ipol,:,onp[0]:onp[1]]).mean(1)
                        ht = freq2time(minphase(spect-spect.min()))
                        ht = np.roll(ht,delay)
                        print "using minimum phase with peak at:",np.abs(ht).argmax()
            else:
                ht = ht0.copy()
            hf = time2freq(ht)
        else:
            hf = _hf_prev.copy()
        ht = freq2time(hf)
        
        if self.nopt == 0 or adjust_delay:
            if rindex is None:
                rindex = np.abs(ht).argmax()
            self.rindex = rindex
        else:
            rindex = self.rindex
        print "max filter index = %d" % self.rindex
        
        if maxneg is not None:
            if maxlen is not None:
                valsamp = maxlen
            else:
                valsamp = ht.shape[0]/2 + maxneg
            minbound = np.zeros_like(ht)
            minbound[:valsamp] = 1+1j
            minbound = np.roll(minbound,rindex-maxneg)
            b = get_params(minbound,rindex)
            bchoice = [0,None]
            bounds = [(bchoice[int(x)],bchoice[int(x)]) for x in b]
        else:
            bounds=None
        #rotate phase time
        phasor = np.conj(ht[rindex])
        ht = ht * phasor / np.abs(phasor)
        
        dim0 = 2*self.nlag-1
        
        var,nvalid = self.cyclic_variance(cs)
        self.noise = np.sqrt(var)
        dof = nvalid - dim0 - self.nphase
        print "variance : %.5e" % var
        print "nsamp    : %.5e" % nvalid
        print "dof      : %.5e" % dof
        print "min obj  : %.5e" % (dof*var)
        
        tol = 1e-1 / (dof)
        print "ftol     : %.5e" % (tol)
        scipytol = tolfact*tol/2.220E-16 #2.220E-16 is machine epsilon, which the scipy optimizer uses as a unit
        print "scipytol : %.5e" % scipytol
        x0 = get_params(ht, rindex)
        
        self.niter = 0
        self.objval = []
        
        x,f,d = scipy.optimize.fmin_l_bfgs_b(cyclic_merit_lag, x0,m=20, args = (self,),
                                             iprint=iprint,maxfun=maxfun,factr = scipytol,bounds=bounds)
        ht = get_ht(x, rindex)
        hf = time2freq(ht)
        
        self.hf_soln = hf[:]
        
        hf = match_two_filters(_hf_prev, hf)
        self.optimized_filters[isub,:] = hf
        self.hf_prev = hf.copy()
        
        ph = optimize_profile(cs,hf,self.bw,self.ref_freq)
        ph[0] = 0.0
        pp = harm2phase(ph)
        
        self.intrinsic_profiles[isub,:] = pp
        self.pp_int += pp
        
        self.nopt += 1
            
            
    def saveResults(self,fbase=None):
        if fbase is None:
            fbase = self.filename
        writeProfile(fbase + '.pp_int.txt', self.pp_int)
        writeProfile(fbase + '.pp_ref.txt', self.pp_ref)
        writeArray(fbase+'.hfs.txt',self.optimized_filters)
        writeArray(fbase+'.dynspec.txt',self.dynamic_spectrum)
        pass
    
        
            
    def cyclic_variance(self,cs):
        ih = self.nharm - 1
        
        imin,imax = chan_limits_cs(iharm = ih,nchan=self.nchan,bw=self.bw,ref_freq=self.ref_freq) #highest harmonic
        var = (np.abs(cs[imin:imax,ih])**2).sum()
        nvalid = imax-imin
        var = var/nvalid
        
        for ih in range(1,self.nharm-1):
            imin,imax = chan_limits_cs(iharm = ih,nchan=self.nchan,bw=self.bw,ref_freq=self.ref_freq)
            nvalid += (imax-imin)
        return var,nvalid*2
            
    def phase_gradient(self,cs,ph_ref = None):
        if ph_ref is None:
            ph_ref = self.ph_ref
        ih = 1
        imin,imax = chan_limits_cs(iharm=ih,nchan=self.nchan,bw=self.bw,ref_freq=self.ref_freq)
        grad_sum = cs[:,ih].sum()
        grad_sum /= ph_ref[ih]
        phase_angle = np.angle(grad_sum)
        # ensure -pi < ph < pi
        if phase_angle > np.pi:
            phase_angle = phase_angle - 2*np.pi
        #express as delay
        phase_angle /= -2 * np.pi * self.ref_freq
        phase_angle *= 1e6 * self.bw
        
        if phase_angle > self.nchan/2:
            delay = self.nchan/2
        elif phase_angle < -(self.nchan/2):
            delay = self.nchan/2 + 1
        elif phase_angle < -0.1:
            delay = int(phase_angle) + self.nchan - 1
        else:
            delay = int(phase_angle)
            
        return delay
            
        
        
        
    def saveState(self,filename=None):
        """
        not yet ready for use
        Save current state of this class (inlcuding current CS solution)
        """
        # For now we just use pickle for convenience. In the future, could use np.savez or HDF5 (or FITS)
        if filename is None:
            if self.statefile:
                filename = self.statefile
            else:
                filename = self.filename + '.cysolve.pkl'
        orig_statefile = self.statefile
        orig_ar = self.ar
        self.ar = None
        fh = open(filename,'w')
        cPickle.dump(self,fh,protocol=-1)
        fh.close()
        self.ar = orig_ar
        self.statefile = orig_statefile
        print "Saved state in:", filename
        

            
    def plotCurrentSolution(self):
        cs_model = self.model
        grad = self.grad
        hf = self.hf
        ht = self.ht
        mlag = self.mlag
        fig = Figure()
        ax1 = fig.add_subplot(3,3,1)
        csextent = [1,mlag-1,self.rf+self.bw/2.0,self.rf-self.bw/2.0]
        im = ax1.imshow(np.log10(np.abs(self.cs[:,1:mlag])),aspect='auto',interpolation='nearest',extent=csextent)
        #im = ax1.imshow(cs2ps(self.cs),aspect='auto',interpolation='nearest',extent=csextent)
        ax1.set_xlim(0,mlag)
        ax1.text(0.9,0.9,"log|CS|",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax1.transAxes, bbox=dict(alpha=0.75,fc='white'))
        im.set_clim(-4,2)
        
        ax1b = fig.add_subplot(3,3,2)
        im = ax1b.imshow(np.angle(self.cs[:,:mlag])-np.median(np.angle(self.cs[:,:mlag]),axis=0)[None,:],cmap=plt.cm.hsv,aspect='auto',interpolation='nearest',extent=csextent)
        #im = ax1b.imshow(self.cs[:,:mlag].imag,aspect='auto',interpolation='nearest',extent=csextent)
        
        im.set_clim(-np.pi,np.pi)
        ax1b.set_xlim(0,mlag)
        ax1b.text(0.9,0.9,"angle(CS)",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax1b.transAxes, bbox=dict(alpha=0.75,fc='white'))
        for tl in ax1b.yaxis.get_ticklabels():
            tl.set_visible(False)
        ax2 = fig.add_subplot(3,3,4)
        im = ax2.imshow(np.log10(np.abs(cs_model[:,1:mlag])),aspect='auto',interpolation='nearest',extent=csextent)
        #im = ax2.imshow(cs2ps(cs_model),aspect='auto',interpolation='nearest',extent=csextent)
        im.set_clim(-4,2)
        ax2.set_xlim(0,mlag)
        ax2.set_ylabel('RF (MHz)')
        ax2.text(0.9,0.9,"log|CS model|",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax2.transAxes, bbox=dict(alpha=0.75,fc='white'))

        ax2b = fig.add_subplot(3,3,5)
        im = ax2b.imshow(np.angle(cs_model[:,:mlag])-np.median(np.angle(cs_model[:,:mlag]),axis=0)[None,:],cmap=plt.cm.hsv,aspect='auto',interpolation='nearest',extent=csextent)
        #im = ax2b.imshow(cs_model[:,:mlag].imag,aspect='auto',interpolation='nearest',extent=csextent)
        im.set_clim(-np.pi,np.pi)
        ax2b.set_xlim(0,mlag)
        ax2b.text(0.9,0.9,"angle(CS model)",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax2b.transAxes, bbox=dict(alpha=0.75,fc='white'))
        for tl in ax2b.yaxis.get_ticklabels():
            tl.set_visible(False)
        sopt = optimize_profile(self.cs,hf,self.bw,self.ref_freq)
        sopt = normalize_profile(sopt)
        sopt[0] = 0.0        
        smeas = normalize_profile(self.cs.mean(0))
        smeas[0] = 0.0
#        cs_model0,csplus,csminus,phases = make_model_cs(hf,sopt,self.bw,self.ref_freq)

        ax3 = fig.add_subplot(3,3,7)
#        ax3.imshow(np.log(np.abs(cs_model0)[:,1:]),aspect='auto')
        err = (np.abs(self.cs-cs_model)[:,1:mlag])
        #err = cs2ps(self.cs) - cs2ps(normalize_cs(cs_model,self.bw,self.ref_freq))
        im = ax3.imshow(err,aspect='auto',interpolation='nearest',extent=csextent)
        ax3.set_xlim(0,mlag)
#        im.set_clim(err[1:-1,1:-1].min(),err[1:-1,1:-1].max())
        im.set_clim(0,3*self.noise)
        ax3.text(0.9,0.9,"|error|",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax3.transAxes, bbox=dict(alpha=0.75,fc='white'))
        ax3.set_xlabel('Harmonic')
        
        ax3b = fig.add_subplot(3,3,8)
        im = ax3b.imshow(np.angle((self.cs[:,:mlag]/cs_model[:,:mlag])),cmap=plt.cm.hsv,aspect='auto',interpolation='nearest',extent=csextent)
        #im = ax3b.imshow((self.cs[:,:mlag]-cs_model[:,:mlag]).imag,aspect='auto',interpolation='nearest',extent=csextent)
        im.set_clim(-np.pi/2.,np.pi/2.)
        ax3b.set_xlim(0,mlag)
        ax3b.text(0.9,0.9,"angle(error)",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax3b.transAxes, bbox=dict(alpha=0.75,fc='white'))
        for tl in ax3b.yaxis.get_ticklabels():
            tl.set_visible(False)
        ax3b.set_xlabel('Harmonic')

        ax4 = fig.add_subplot(4,3,3)
        t = np.arange(ht.shape[0])/self.bw
        ax4.plot(t,np.roll(20*np.log10(np.abs(ht)),(ht.shape[0]/2)-self.rindex))
        ax4.plot(t,np.roll(20*np.log10(np.convolve(np.ones((10,))/10.0,np.abs(ht),mode='same')),(ht.shape[0]/2)-self.rindex),linewidth=2,color='r',alpha=0.4)
        
        ax4.set_ylim(0,80)
        ax4.set_xlim(t[0],t[-1])
        ax4.text(0.9,0.9,"dB|h(t)|$^2$",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax4.transAxes)
        ax4.text(0.95,0.01,"$\\mu$s",
                 fontdict=dict(size='small'),va='bottom',ha='right',
                 transform=ax4.transAxes)
        ax4b = fig.add_subplot(4,3,6)
        f = np.linspace(self.rf+self.bw/2.0,self.rf-self.bw/2.0,self.nchan)
        ax4b.plot(f,np.abs(hf))
        ax4b.text(0.9,0.9,"|H(f)|",
                 fontdict=dict(size='small'),va='top',ha='right',
                 transform=ax4b.transAxes)
        ax4b.text(0.95,0.01,"MHz",
                 fontdict=dict(size='small'),va='bottom',ha='right',
                 transform=ax4b.transAxes)
        ax4b.set_xlim(f.min(),f.max())
        ax4b.xaxis.set_major_locator(plt.MaxNLocator(4))
        ax5 = fig.add_subplot(4,3,9)
        if len(self.objval) >= 3:
            x = np.abs(np.diff(np.array(self.objval).flatten()))
            ax5.plot(np.arange(x.shape[0]),np.log10(x))
        ax5.text(0.9,0.9,"log($\\Delta$merit)",
                 fontdict=dict(size='small'),va='top',ha='right',transform=ax5.transAxes)
        ax6 = fig.add_subplot(4,3,12)
        pref =  harm2phase(self.s0)
        ax6.plot(pref,label='Reference',linewidth=2)
        ax6.plot(harm2phase(sopt),'r',label='Intrinsic')
        ax6.plot(harm2phase(smeas),'g',label='Measured')
        l = ax6.legend(loc='upper left',prop=dict(size='xx-small'),title='Profiles')
        l.get_frame().set_alpha(0.5)
        ax6.set_xlim(0,pref.shape[0])
        fname = self.filename[-50:]
        if len(self.filename) > 50:
            fname = '...' + fname
        title = "%s isub: %d ipol: %d nopt: %d\n" % (fname, self.isub,self.ipol,self.nopt)
        title += ("Source: %s Freq: %s MHz Feval #%04d Merit: %.3e Grad: %.3e" % 
                  (self.source, self.rf, self.niter, self.objval[-1], np.abs(grad).sum()))
        fig.suptitle(title, size='small')
        canvas = FigureCanvasAgg(fig)
        fname = os.path.join(self.plotdir,('%s_%04d_%04d.png' % (self.source, self.nopt, self.niter)))
        canvas.print_figure(fname)


def fold(v):
    """
    Fold negative response onto positive time for minimum phase calculation
    """        
    n = v.shape[0]
    nt = n/2
    rf = np.zeros_like(v[:nt])
    rf[:-1] = v[1:nt]
    rf += np.conj(v[:nt-1:-1])
    rw = np.zeros_like(v)
    rw[0] = v[0]
    rw[1:nt+1] = rf
    return rw    

def minphase(v):
    clipped = v.copy()
    thresh = 1e-5
    clipped[np.abs(v) < thresh] = thresh
    return np.exp(np.fft.fft(fold(np.fft.ifft(np.log(clipped)))))        
def loadArray(fname):
    """
    Load array from txt file in format generated by filter_profile,
    useful for filters.txt, dynamic_spectrum.txt
    """
    fh = open(fname,'r')
    try:
        x = int(fh.readline())
    except:
        raise Exception("couldn't read first dimension")
    try:
        y = int(fh.readline())
    except:
        raise Exception("couldn't read second dimension")
    raw = np.loadtxt(fh)
    if raw.shape[0] != x*y:
        raise Exception("number of rows of data=",raw.shape[0]," not equal to product of dimensions:",x,y)
    if len(raw.shape) > 1:
        data = raw[:,0] + raw[:,1]*1j
    else:
        data = raw[:]
    data.shape = (x,y)
    fh.close()
    return data

def writeArray(fname,arr):
    """
    Write array to ascii file in same format as filter_profile does
    """
    fh = open(fname,'w')
    fh.write('%d\n' % arr.shape[0])
    fh.write('%d\n' % arr.shape[1])
    for x in range(arr.shape[0]):
        for y in range(arr.shape[1]):
            if arr.dtype == np.complex:
                fh.write('%.7e %.7e\n' % (arr[x,y].real, arr[x,y].imag))
            else:
                fh.write('%.7e\n' % (arr[x,y]))
    fh.close()
    
def writeProfile(fname,prof):
    """
    Write profile to ascii file in same format as filter_profile does
    """
    t = np.linspace(0,1,prof.shape[0],endpoint=False)
    fh = open(fname,'w')
    for x in range(prof.shape[0]):
        fh.write('%.7e %.7e\n' % (t[x],prof[x]))
    fh.close()


def loadProfile(fname):
    """
    Load profile in format generated by filter_profile
    """
    
    x = np.loadtxt(fname)
    return x[:,1]

# np.fft does /n for all iffts, unlike fftw. So for now we keep normalization same for cross check
# by multiplying by n

# Note: for routines using rfft (ps2cs and phase2harm), the filter_profile code attempts to
# normalize the result so that ps2cs(cs2ps(x)) = x by dividing by the length of the output array
# However the fftw documentation indicates that one should instead divide by the length of the
# input array.
# I've left the bug in for now to compare directly to filter_profile
 
def cs2cc(cs):
    return cs.shape[0] * np.fft.ifft(cs,axis=0)
def cc2cs(cc):
    cs = np.fft.fft(cc,axis=0)
    #cc2cs_renorm
    return cs/cs.shape[0]

def ps2cs(ps):
    cs =  np.fft.rfft(ps,axis=1)
    #ps2cs renorm
    return cs/cs.shape[1] # original version from Cyclic-modelling
    #return cs/(2*(cs.shape[1] - 1))

def cs2ps(cs):
    return (cs.shape[1] -1) * 2 * np.fft.irfft(cs,axis=1)

def time2freq(ht):
    hf = np.fft.fft(ht)
    #filter_freq_renorm
    return hf/hf.shape[0]

def freq2time(hf):
    return hf.shape[0] * np.fft.ifft(hf)

def harm2phase(ph):
    return (ph.shape[0] - 1) * 2 * np.fft.irfft(ph)

def phase2harm(pp):
    ph = np.fft.rfft(pp)
    #profile_harm_renorm
    return ph/ph.shape[0]  #original version from Cyclic-modelling
    #return ph/(2*(ph.shape[0]-1))

def match_two_filters(hf1,hf2):
    z = (hf1 * np.conj(hf2)).sum()
    z2 = (hf2 * np.conj(hf2)).sum() # = np.abs(hf2)**2.sum()
    z /= np.abs(z)
    z *= np.sqrt(1.0*hf1.shape[0]/np.real(z2))
    return hf2*z

def normalize_profile(ph):
    """
    Normalize harmonic profile such that first harmonic has magnitude 1
    """
    return ph/np.abs(ph[1])
    
def normalize_pp(pp):
    """
    Normalize a profile but keep it in phase rather than harmonics
    """
    ph = phase2harm(pp)
    ph = normalize_profile(ph)
    ph[0] = 0
    return harm2phase(ph)

def normalize_cs(cs,bw,ref_freq):
    rms1 = rms_cs(cs,ih=1,bw=bw,ref_freq=ref_freq)
    rmsn = rms_cs(cs,ih=cs.shape[1]-1,bw=bw,ref_freq=ref_freq)
    normfac = np.sqrt(np.abs(rms1**2-rmsn**2))
    return cs/normfac

def rms_cs(cs,ih,bw,ref_freq):
    nchan = cs.shape[0]
    imin,imax = chan_limits_cs(ih,nchan,bw,ref_freq)
    rms = np.sqrt((np.abs(cs[imin:imax,ih])**2).mean())
    return rms

def cyclic_padding(cs,bw,ref_freq):
    nharm = cs.shape[1]
    nchan = cs.shape[0]
    for ih in range(nharm):
        imin,imax = chan_limits_cs(ih,nchan,bw,ref_freq)
        cs[:imin,ih] = 0
        cs[imax:,ih] = 0
    return cs

def chan_limits_cs(iharm,nchan,bw,ref_freq):
    inv_aspect = ref_freq * nchan
    inv_aspect *= iharm / (bw*1e6)
    inv_aspect -= 1
    inv_aspect /= 2.0
    ichan = int(inv_aspect) + 1
    if ichan > nchan/2:
        ichan = nchan/2
    return (ichan,nchan-ichan) #min,max


def cyclic_shear_cs(cs,shear,bw,ref_freq):
    nharm = cs.shape[1]
    nlag = cs.shape[0]
    dtau = 1/(bw*1e6)
    dalpha = ref_freq
    #cs2cc
    cc = cs2cc(cs)
    lags = np.arange(nlag)
    lags[nlag/2+1:] = lags[nlag/2+1:] - nlag
    tau1 = dtau*lags
    alpha1 = dalpha*np.arange(nharm) 

    phases = np.outer( shear* (-2.0*np.pi) * tau1, alpha1)
    
    cc = cc * np.exp(1j*phases)
    
    return cc2cs(cc),phases
    
    
    
def make_model_cs(hf,s0,bw,ref_freq):
    nchan = hf.shape[0]
    nharm = s0.shape[0]
    #profile2cs
    cs = np.repeat(s0[np.newaxis,:],nchan,axis=0) # fill the cs model with the harmonic profile for each freq chan
    #filter2cs
    cs_tmp = np.repeat(hf[:,np.newaxis],nharm,axis=1) # fill the cs_tmp model with the filter for each harmonic
    
    csplus,plus_phases = cyclic_shear_cs(cs_tmp,shear=0.5,bw=bw,ref_freq=ref_freq)
    csminus,minus_phases = cyclic_shear_cs(cs_tmp,shear=-0.5,bw=bw,ref_freq=ref_freq) # this is redundant, minus phases is just negative of plus phases
    
    cs = cs * csplus * np.conj(csminus)
    
    cs = cyclic_padding(cs,bw,ref_freq)
    
    return cs,csplus,csminus,minus_phases # minus_phases has factor of 2*pi*tau*alpha 

def optimize_profile(cs,hf,bw,ref_freq):
    nchan = cs.shape[0]
    nharm = cs.shape[1]
    #filter2cs
    cs1 = np.repeat(hf[:,np.newaxis],nharm,axis=1) # fill the cs_tmp model with the filter for each harmonic
    csplus,plus_phases = cyclic_shear_cs(cs1,shear=0.5,bw=bw,ref_freq=ref_freq)
    
    csminus,minus_phases = cyclic_shear_cs(cs1,shear=-0.5,bw=bw,ref_freq=ref_freq)
    
    #cs H(-)H(+)*
    cshmhp =  cs * csminus * np.conj(csplus)
    #|H(-)|^2 |H(+)|^2
    maghmhp = (np.abs(csminus)*np.abs(csplus))**2
    #fscrunch
    denom = fscrunch_cs(maghmhp,bw=bw,ref_freq=ref_freq)
    numer = fscrunch_cs(cshmhp,bw=bw,ref_freq=ref_freq)
    s0 = numer/denom
    s0[np.real(denom) <= 0.0] = 0
    return s0
    
def fscrunch_cs(cs,bw,ref_freq):
    cstmp = cs[:]
    cstmp = cyclic_padding(cstmp,bw,ref_freq)
#    rm = np.abs(cs-cstmp).sum()
#    print "fscrunch saved:",rm
    return cstmp.sum(0)
    
def get_params(ht,rindex):
    nlag = ht.shape[0]
    params = np.zeros((2*nlag - 1,), dtype='float')
    if rindex > 0:
        params[:2*(rindex)] = ht[:rindex].view('float')
    params[2*rindex] = ht[rindex].real
    if rindex < nlag-1:
        params[2*rindex+1:] = ht[rindex+1:].view('float')
    return params
def get_ht(params,rindex):
    nlag = (params.shape[0]+1)/2
    ht = np.zeros((nlag,),dtype='complex')
    ht[:rindex] = params[:2*rindex].view('complex')
    ht[rindex] = params[2*rindex]
    ht[rindex+1:] = params[2*rindex+1:].view('complex')
    return ht
    
def cyclic_merit_lag(x,*args):
    """
    The objective function. Computes mean squared merit and gradient
    
    Format is compatible with scipy.optimize
    """
    CS = args[0]
    print "rindex",CS.rindex
    ht = get_ht(x,CS.rindex)
    hf = time2freq(ht)
    CS.hf = hf
    CS.ht = ht
    cs_model,csplus,csminus,phases = make_model_cs(hf,CS.s0,CS.bw,CS.ref_freq)
    merit = 2*(np.abs(cs_model[:,1:] - CS.cs[:,1:])**2).sum() #ignore zeroth harmonic (dc term)
    
    # the objval list keeps track of how the convergence is going
    CS.objval.append(merit)
    
    #gradient_lag
    diff = cs_model - CS.cs #model - data
    cc1 = cs2cc(diff * csminus)
    
# original c code for reference:
#    for (ilag=0; ilag<cc1.nlag; ilag++) {
#        gradient->data[ilag] = 0.0 + I * 0.0;
#        int lag = (ilag<=cc1.nlag/2) ? ilag : ilag-cc1.nlag;
#        tau = (double)lag * (double)cs->nchan /
#        ( (double)cc1.nlag * cc1.bw*1.e6 );
#        for (ih=1; ih<cc1.nharm; ih++) {
#            phs = M_PI * tau * (double)ih * cc1.ref_freq;
#            phasor = cos(phs)+I*sin(phs);
#            fftwf_complex *ccval = get_cc(&cc1,ih,ip,ilag);
#            gradient->data[ilag] += 4.0 * (*ccval) * phasor
#            * conj(s0->data[ih]) / (float)cs->nchan;
#        }
#     }

    #we reuse phases and csminus, csplus from the make_model_cs call

    phasors = np.exp(1j*phases)
    cs0 = np.repeat(CS.s0[np.newaxis,:],CS.nlag,axis=0) #filter2cs
    grad = 4.0 * cc1 * phasors * np.conj(cs0) / CS.nchan
    grad = grad[:,1:].sum(1) # sum over all harmonics to get function of lag
    
    #conjugate(res)
    #calc positive shear
    #multiply
    #cs2cc
    cc2 = cs2cc(np.conj(diff) * csplus)
    grad2 = 4.0 * cc2 * np.conj(phasors) * cs0 / CS.nchan
    
    grad = grad + grad2[:,1:].sum(1)
    CS.grad = grad[:]
    CS.model = cs_model[:]

    if CS.iprint:
        print "merit= %.7e  grad= %.7e" % (merit,(np.abs(grad)**2).sum())
            
    if CS.make_plots:
        CS.plotCurrentSolution()
        
        
    
    grad = get_params(grad, CS.rindex)
    CS.niter += 1
    
    return merit,grad

def loadCyclicSolver(statefile):
    """
    Load previously saved Cyclic Solver class
    """
    fh = open(statefile,'r')
    cys = cPickle.load(fh)
    fh.close()
    return cys


if __name__ == "__main__":
    import sys
    fname = sys.argv[1]
    CS = CyclicSolver(filename=fname)
    if len(sys.argv) > 2:
        CS.initProfile(loadFile = sys.argv[2])
    else:
        CS.initProfile()
    np.save(('%s_profile.npy' % CS.source),CS.pp_ref)
    CS.loop(make_plots=True,tolfact=20)
    CS.saveResults()
