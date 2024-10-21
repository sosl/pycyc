/***************************************************************************
 *
 *   Copyright (C) 2024 by Willem van Straten
 *   Licensed under the Academic Free License version 2.1
 *
 ***************************************************************************/

#include "Pulsar/Application.h"
#include "Pulsar/DynamicResponse.h"
#include "random.h"

#include <fftw3.h>
#include <cassert>

using namespace std;

//
//! Dynamic Response Simulator
//
class dyn_res_sim : public Pulsar::Application
{
public:

  //! Default constructor
  dyn_res_sim ();

  //! Process the given archive
  void process (Pulsar::Archive*);

protected:

  //! Sampling interval in seconds
  double sampling_interval = 15.0;

  //! Number of time samples
  unsigned ntime = 256;

  //! Timescale of exponential decay of impulse response
  double impulse_response_decay = 0.0;

  //! Curvature of scintillation arc
  double arc_curvature = 0.0;

  //! Add command line options
  void add_options (CommandLine::Menu&);
};

dyn_res_sim::dyn_res_sim ()
  : Application ("dyn_res_sim", "Dynamic Response Simulator")
{

}

void dyn_res_sim::add_options (CommandLine::Menu& menu)
{
  CommandLine::Argument* arg;

  menu.add ("\n" "General options:");

  arg = menu.add (sampling_interval, 't');
  arg->set_help ("Sampling interval in seconds");

  arg = menu.add (ntime, 'n');
  arg->set_help ("Number of time samples");
}

std::complex<double> random_phasor()
{
  double phase = random_double () * 2.0 * M_PI;
  return { cos(phase), sin(phase) };
}

void dyn_res_sim::process (Pulsar::Archive* archive)
{
  if (!name.empty())
    archive->set_source (name);

  unsigned nchan = archive->get_nchan();
  unsigned npol = archive->get_npol();

  double cfreq = archive->get_centre_frequency();
  double bw = archive->get_bandwidth();
  double chanbw = bw / nchan;

  double minfreq = cfreq - 0.5 * (bw - chanbw);
  double maxfreq = cfreq + 0.5 * (bw - chanbw);

  Reference::To<Pulsar::DynamicResponse> ext = new Pulsar::DynamicResponse;
  ext->set_minimum_frequency(minfreq);
  ext->set_maximum_frequency(maxfreq);

  ext->set_nchan(nchan);
  ext->set_ntime(ntime);
  ext->set_npol(1);
  ext->resize_data();

  auto data = reinterpret_cast<std::complex<double>*>( ext->get_data().data() );

  for (unsigned ichan=0; ichan < nchan; ichan++)
    for (unsigned itime=0; itime < ntime; itime++)
      data[itime*nchan + ichan] = 0;

  // sampling interval along delay axis, in seconds
  double delta_tau = 1e-6/bw;
  // maximum positive delay
  double max_tau = 0.5 * nchan * delta_tau; 

  // time spanned by response
  double time_span = ntime * sampling_interval;

  // sampling interval along Doppler shift axis, in Hz
  double delta_omega = 1.0/time_span;
  // maximum positive Doppler shift
  double max_omega = 0.5 * ntime * delta_omega;

  double curvature = arc_curvature;
  if (curvature == 0)
  {
    double default_omega_span = 0.9;
    cerr << "dyn_res_sim::process setting arc curvature to span " << default_omega_span*100.0 << "\% of Doppler axis at maximum delay" << endl;
    double span_omega = default_omega_span * max_omega;
    curvature = max_tau / (span_omega * span_omega);
  }

  cerr << "dyn_res_sim::process arc curvature = " << curvature << " s^3" << endl;

  double decay = impulse_response_decay;
  if (decay == 0)
  {
    double default_decay = 0.25;
    cerr << "dyn_res_sim::process setting decay time scale to " << default_decay*100.0 << "\% of maximum delay" << endl;
    decay = max_tau * default_decay;
  }

  cerr << "dyn_res_sim::process decay time scale = " << decay << " s" << endl;

  unsigned iomega = 0;
  unsigned nomega = ntime / 2;

  unsigned itau = 0;
  unsigned ntau = nchan / 2;

  cerr << "dyn_res_sim::process nomega=" << nomega << " ntau=" << ntau << endl;

  bool f_of_omega = true;

  double omega = 0.0;
  double tau = 0.0;
  unsigned jtau = 0;
  unsigned jomega = 0;

  while (iomega < nomega && itau < ntau)
  {
    if (f_of_omega)
    {
      omega = iomega * delta_omega;
      tau = curvature * omega*omega;
      jtau = tau / delta_tau;
      jomega = iomega;

      // when the step in tau is larger than the sampling interval (i.e. a delay is skipped)
      if (jtau > itau)
      {
        cerr << "switch to function of tau when iomega=" << iomega << " and itau=" << itau << endl;
        f_of_omega = false;
      }

      iomega ++;
      itau = jtau + 1;
    }

    if (!f_of_omega)
    {
      tau = itau * delta_tau;
      omega = sqrt(tau/curvature);
      jtau = itau;
      jomega = omega / delta_omega;
      if (jomega >= nomega)
        break;

      itau ++;
      iomega = jomega;
    }

    double amplitude = exp(-decay * tau);

    data[jomega*nchan + jtau] = amplitude;
    if (jomega > 0)
    {
      data[jomega*nchan + jtau] *= random_phasor();
      data[(ntime-jomega)*nchan + jtau] = amplitude * random_phasor();
    }
  }

  cerr << "loop finished with iomega=" << iomega << " and itau=" << itau << endl;

  // perform an in-place 2D FFT

  /* 
  In principle, we wish to perform a forward FFT along the delay axis and a backward FFT
  along the differential Doppler delay axis.  This could be achieved by complex conjugating
  and reversing the elements along differential Doppler delay axis.  However, since the
  phases are random, it doesn't matter (at least, as long as only the dynamic frequency 
  response is used from this point onward, and there is no need to return to the
  delay-Doppler wavefield).
  */

  auto fftin = reinterpret_cast<fftw_complex *>( ext->get_data().data() );
  auto plan = fftw_plan_dft_2d(ntime, nchan, fftin, fftin, FFTW_FORWARD, FFTW_MEASURE);
  fftw_execute(plan);
  fftw_destroy_plan(plan);

  Reference::To<Pulsar::Archive> clone = archive->clone();
  clone->resize(0);
  clone->add_extension(ext);

  std::string filename = "dyn_resp_sim.fits";
  clone->unload(filename);

  Reference::To<Pulsar::Archive> test = Pulsar::Archive::load(filename);
  auto test_ext = test->get<Pulsar::DynamicResponse>();
  auto test_data = reinterpret_cast<std::complex<double>*>( test_ext->get_data().data() );
  for (unsigned ichan=0; ichan < nchan; ichan++)
    for (unsigned itime=0; itime < ntime; itime++)
    {
      unsigned idx = itime*nchan + ichan;
      assert(test_data[idx] == data[idx]);
    }
}


/*!

  The standard C/C++ main function simply calls Application::main

*/

int main (int argc, char** argv)
{
  // seeds the random number generator with the current microsecond
  random_init ();

  dyn_res_sim program;
  return program.main (argc, argv);
}
