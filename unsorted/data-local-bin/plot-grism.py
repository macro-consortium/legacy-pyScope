#!/usr/bin/env python  

# plt-grism-spectrum: Plots calibrated GRISM spectrum, with optional strip spectrum image

'''
v 0.2  21 Mar 2016 RLM
v 1.0  20 Apr 2016 Don't solve for star position in field image (images are assumed to be centered) 
v 3.0  15 Nov 2016 Use new simplified quadratic wavelength calibration based on fit in 15-Nov-2016 MathCAD document, add WR line options (C,N,O,E)
v 3.10 13 Dec 2016 Delete spaces in object name when constructing plot name; add option for publication-quality plots: thick lines, larger fonts
v 3.11 14 Dec 2016 Publication prep tweaks: Add rc.Params for larger plot fonts, thicker lines; Add -T: omit title line; add -o output plot name
v.3.20 16 Dec 2016 Move all grism coefficients [angle, y0, a,b] to separate grism_coeffs.csv file - reads filter code
v.3.21 20 Jan 2017 remover -g switch: grism file name is at the end of commend line
v.3.3  19 Jul 2017 add option to select coefficients file; add option to increase font size for publication;
                     handle bad request for 2x2 plots with no reference spectrum gracefully
v.4.0  10 Apr 2018 Support for IKON camera
v.4.01 25 Apr 2018 Improve error message when filter doesn't match coeffs.csv file
v.4.1  07 Dec 2018 small changes: font size, add switch to generate gain curve
'''
# N.B. Only supports the 600 lpmm (Filter '6') grism: need to add the 300 lpmm grisms (codes A,3)

vers = 'plot-grism version 4.1, 7 Dec 2018'

import numpy,getopt
from astropy.io import fits  

from  math import sin,atan,pi
import numpy as np
from scipy.ndimage.interpolation import rotate
from scipy.signal import medfilt
from scipy.optimize import minimize
import sys, os, re, glob, warnings
import scipy.ndimage as snd 
from optparse import OptionParser
from matplotlib import gridspec
from matplotlib import rcParams

#print rcParams.keys()
# Set matplotlib parameters  for publication
params = {
   'lines.linewidth': 1.5,
   'axes.linewidth': 1.5,
   'axes.labelsize': 16,
   'text.fontsize': 16,
   'legend.fontsize': 10,
   'xtick.labelsize': 14,
   'ytick.labelsize': 14,
   'text.usetex': False,
   'figure.figsize': [4.5, 4.5]
   }
rcParams.update(params)

# Avoid annoying warning about matplotlib building the font cache
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import matplotlib.pyplot as plt
    from matplotlib.pyplot import cm as cmap
    import matplotlib.font_manager

def get_args():
	parser = OptionParser(description='Program %prog plots grism spectra',version = vers)
	parser.add_option('-b', dest = 'b', metavar='begin wavelength', action = 'store', type=float, default = 400.0, help = 'Beginning plot wavelength [nm],default 400nm') 
	parser.add_option('-e', dest = 'e', metavar='end wavelength'  , action = 'store', type=float, default = 700.0, help = 'End plot wavelength [nm], default 700nm'      )
	parser.add_option('-B', dest = 'B', metavar='Balmer lines', action = 'store_true', default = False, help='Plot Balmer lines')
	parser.add_option("-c", dest = "cal_table",  default = gain_tbl_path, metavar="Cal table", help = "Calibration table (CSV file)")         
	parser.add_option('-g', dest = 'gain', metavar='Gain curve', action = 'store_true', default = False, help='Generate gain curve table')
	parser.add_option("-x", dest = "coeffs_table", default = grism_coeffs_path, metavar="Coeffs table", help = "Coefficients table (CSV file)")    
	parser.add_option('-H', dest = 'Hanning', type=int, default = 1, action='store', metavar="Hanning smoothing", help="Hanning smoothing window width [nm]")      
	parser.add_option('-t', dest = 'tweak', metavar='tweak pointing', action = 'store', default = '0,0', help='Tweak star position (0,0) [pixels]' )
	parser.add_option("-T", dest = 'title', metavar='Plot title', default = '', help='Plot title [default: object coords date Z etc')  
	parser.add_option("-o", dest = "outfile",  default = '',   metavar="Output plot file", help="Ouput plot name [defaults to object_date]") 
	parser.add_option("-p", dest = "plot_format",  default = 0,  type=int, metavar="Plot format", help="Plot format: 0=PNG, 1=PDF (default 0)")  
	parser.add_option('-P', dest = 'plot', metavar='Plot options', action = 'store', type=int, default = 0, help='Plot enhancements: 1: strip image, 2: 2x2')
	parser.add_option('-L', dest = 'large_font', metavar='verbose', action = 'store_true', default = False, help='Large font option (def. false)')
	parser.add_option("-r", dest = "ref_spec",  default = '',   metavar="Ref. spectrum", help="Reference spectrum file (plotted with P=2)")
	parser.add_option('-v', dest = 'verbose', metavar='verbose', action = 'store_true', default = False, help='Verbose output')
	parser.add_option("-w", dest = 'width', type=float, default = 15,  metavar="Spectrum width", help="Spectrum width,pixels [15]")   
	parser.add_option("-y", dest = 'yminmax', default = '0.0,1.2',  metavar="y-axis min, max", help="Plot y-axis min,max, default: 0,1.2")
	parser.add_option("-z", dest = 'redshift', type=float, default = 0.0,  metavar="redshift", help="Redshift")
	parser.add_option("-C", dest = 'C',metavar='Carbon lines', action = 'store_true', default = False, help='Plot carbon lines')
	parser.add_option("-N", dest = 'N',metavar='Nitrogen lines', action = 'store_true', default = False, help='Plot nitrogen lines')         
	parser.add_option("-O", dest = 'O',metavar='Oxygen lines', action = 'store_true', default = False, help='Plot oxygen lines')         
	parser.add_option("-E", dest = 'E',metavar='Helium lines', action = 'store_true', default = False, help='Plot helium lines')               

	return parser.parse_args()

def smooth(x,window_len,window='hanning'):
	"""smooth the data using a window with requested size.
     
	This method is based on the convolution of a scaled window with the signal.
    The signal is prepared by introducing reflected copies of the signal 
    (with the window size) in both ends so that transient parts are minimized
    in the begining and end part of the output signal.
   
    input:
	x: the input signal 
	window_len: the dimension of the smoothing window; should be an odd integer
	window: the type of window from 'flat', 'hanning', 'hamming', 'bartlett', 'blackman'
	flat window will produce a moving average smoothing.
	output:
         the smoothed signal         
	example:
      	 t=linspace(-2,2,0.1)
         x=sin(t)+randn(len(t))*0.1
         y=smooth(x)
       
         see also: 
       
         numpy.hanning, numpy.hamming, numpy.bartlett, numpy.blackman, numpy.convolve
         scipy.signal.lfilter
	""" 
  	window_len = int(window_len)
	if x.ndim != 1:
		raise ValueError, "smooth only accepts 1 dimension arrays."

	if x.size < window_len:
		raise ValueError, "Input vector needs to be bigger than window size."

	if window_len<3:
		return x
	
	if not window in ['flat', 'hanning', 'hamming', 'bartlett', 'blackman']:
		raise ValueError, "Window is on of 'flat', 'hanning', 'hamming', 'bartlett', 'blackman'"
	
	s=np.r_[x[window_len-1:0:-1],x,x[-1:-window_len:-1]]
	#print(len(s))
	if window == 'flat': #moving average
		w=np.ones(window_len,'d')
	else:
		w=eval('np.'+window+'(window_len)')
 
	y=np.convolve(w/w.sum(),s,mode='valid')
	return y       

def f_lambda(pix, a, nbin):
    # Return pixel number corresponding to input wavelength in nm [see MathCAD document: Gemini GRISM calibration 16-Nov-2106]
    # N.B. ignores binning param so now [TBA]
    #a0 = 203.14; a1 = 0.391; a2 = 6.544e-5
    lam = a[0] + a[1] * pix  + a[2] * pix**2
    return lam

def f_pixel(lam, b, nbin):
	# Return wavelength corresponding to input pixel number [see MathCAD document: Gemini GRISM calibration 16-Nov-2106]
    # N.B. ignores binning param so now [TBA]
    #b0 = -507.5; b1 = 2.669; b2 = -5.811e-4
    pix = b[0] + b[1] * lam  + b[2] * lam**2 
    return pix
    
def interp_spectrum(raw_spec, gain_table):
	# Unpack 2-d spectra
	raw_wave, raw_amp = raw_spec
	# Gain table
	gain_wave, gain_amp = gain_table
	wmin = gain_wave[0]; wmax = gain_wave[-1]; npts_gain = len(gain_wave)
	dw = (wmax - wmin)/float(npts_gain)
	
	# Interpolate input spectrum so the wavelength spacing is same as calibration spectrum (0.14 nm spacing)
	wave = np.linspace(wmin, wmax, npts_gain)
	amp = np.interp(wave,raw_wave,raw_amp)
	return np.array((wave,amp))

def plot_lines(ax,plt_lines):
	# Plot requested lines on current axis [ax]
	# UGLY code! change to dictionary structure in next rev.
	plt_balmer, plt_carbon, plt_helium, plt_nitrogen, plt_oxygen = plt_lines
	
	if plt_balmer:   
		for line in balmer_lines:
			if line == balmer_lines[0]:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='r',label = 'Balmer')
			else:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='r')
	if plt_carbon:   
		for line in carbon_lines:
			if line == carbon_lines[0]:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='k',label = 'Carbon')
			else:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='k')
	if plt_helium:   
		for line in helium_lines:
			if line == helium_lines[0]:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='g',label = 'Helium')
			else:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='g')
	if plt_nitrogen:   
		for line in nitrogen_lines:
			if line == nitrogen_lines[0]:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='c',label = 'Nitrogen')
			else:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='c')
	if plt_oxygen:   
		for line in oxygen_lines:
			if line == oxygen_lines[0]:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='m',label = 'Oxygen')
			else:
				ax.axvline(line,linestyle='dashed', linewidth='1',color ='m')
	
	ax.legend(loc=3,fontsize=8)
	
	return

def plot_all(object, smooth_nm, raw_spec, cal_spec, ref_spec, ref_spec_file, plt_lines, redshift, gain_tbl, wmin, wmax, yscale, title, plot_filename):
	
	# Plot raw and calibrated spectrum, and gain table
	fig, ((ax1,ax2),(ax3,ax4)) = plt.subplots(2,2,figsize=(12,8))
	fig.suptitle(title)
	ymin, ymax= yscale
	
	# Raw spectrum
	ax1.set_title('%s Uncalibrated spectrum' % object,fontsize =12)
	ax1.plot(raw_spec[0], raw_spec[1], linestyle ='solid', color ='black')
	ax1.grid(True)
	ax1.set_xlim(wmin,wmax); ax1.set_ylim(ymin,ymax)
	
	# Gain table
	ax2.set_title('Gain table',fontsize =12)
	ax2.plot(gain_tbl[0], gain_tbl[1], linestyle ='solid', color = 'black')
	ax2.set_xlim(wmin,wmax)
	ax2.set_ylim(0,5)
	ax2.grid(True)

	
	# Calibrated spectrum
	ax3.set_title('%s Calibrated spectrum (smoothing=%0.1f)' % (object, smooth_nm),fontsize =12 )
	ax3.plot(cal_spec[0], cal_spec[1], linestyle ='solid', color ='black')
	ax3.grid(True)
	ax3.set_xlim(wmin,wmax); ax3.set_ylim(ymin,ymax)
	if any(plt_lines): plot_lines(ax3, plt_lines)
	
	# Reference spectrum
	if len(ref_spec) !=0:
		ref_file = os.path.basename(ref_spec_file)
		ax4.set_title('Reference spectrum (%s)' % ref_file,fontsize =12)
		ax4.plot(ref_spec[0], ref_spec[1], linestyle ='solid', color ='black')
		ax4.grid(True)
		ax4.set_xlim(wmin,wmax); ax4.set_ylim(0,1.2*np.max(ref_spec[1]))
		if any(plt_lines): plot_lines(ax4, plt_lines)

	plt.savefig(plot_filename)
	plt.close(fig)
	print 'Wrote plot file %s' % plot_filename
	return



# Get useful header information
def get_hdr_info(ftsfile):
	im,hdr = fits.getdata(ftsfile,0,header=True)
	object = hdr['OBJECT']
	nbin = hdr['XBINNING']
	D = hdr['DATE-OBS']; date = D[0:10]; ut = D[11:]
	ra = hdr['RA']; dec = hdr['DEC']
	exptime = hdr['EXPTIME']
	filter = hdr['FILTER']
	z = hdr['AIRMASS']
	return object, nbin, date, ut, ra, dec, exptime, filter, z

def plot_spec(object, smooth_nm, cal_spec, im_strip, do_strip, plt_lines, redshift, wmin, wmax, yscale, title, plot_filename):
		wave, cal_amp = cal_spec
		ymin, ymax = yscale
		plt_balmer, plt_carbon, plt_helium, plt_nitrogen, plt_oxygen = plt_lines
		if do_strip:
			fig, (ax1,ax2) = plt.subplots(2,1,figsize=(12,8))
			ax1.imshow(im_strip)
		else:
			fig, (ax2) = plt.subplots(1,1,figsize=(12,8))
		ax2.grid(True)
		ax2.plot(wave,cal_amp,'k-')
		if any(plt_lines): plot_lines(ax2, plt_lines)
	
		ax2.set_xlim(wmin,wmax); ax2.set_ylim(ymin,ymax)
		ax2.set_xlabel('Wavelength (nm)')
		ax2.set_ylabel('Normalized intensity')
		ax2.set_title(title, fontsize=10)
		if do_strip: plt.tight_layout()
		plt.savefig(plt_filename)
		plt.close(fig)
		print 'Wrote plot file %s' % plot_filename
		return

def get_refspec(ref_file):
	''' Retrieve reference spectrum using input ref_file '''
	fn = open(ref_file,'r')
	lines = fn.readlines()[2:]
	fn.close()
	
	nch = len(lines)
	wave_cal = np.zeros(nch); gain_cal = np.zeros(nch)
	for k in range(nch):
		line =  lines[k].strip('/n')
		wave_cal[k],gain_cal[k] = [float(x) for x in line.split()]
	wave_cal = np.array(wave_cal); gain_cal = np.array(gain_cal)
	gain_cal /= np.max(gain_cal)
	ref_spec = (wave_cal, gain_cal)
	return ref_spec

def get_calib_coeffs(filter, calfile):
	try:
		fn = open(calfile,'r')
		lines = fn.readlines()
		fn.close()	
		for line in lines:
			line = line.split(',')
			if line[0] == filter[0].upper():
				c = [float(s) for s in line[1:]]
				angle = c[0]; y0 = c[1]; a = c[2:5]; b = c[5:8]
		return angle, y0, a, b
	except:
		sys.exit('Problem finding filter %s in coeffs file %s, exiting' % (filter[0].upper(),calfile))
	

#  ======= MAIN =======

# MKS Conversions, program constants
cm = 1.e-2; mm = 1.e-3; micron = 1.e-6; nm = 1.e-9
deg = pi/180.; arcmin = deg/60.; arcsec = deg/3600.
width = 300; wmin = 380; wmax = 900.


# Spectral lines to overlay if requested
line_labels = ['Balmer', 'Carbon', 'Nitrogen', 'Helium', 'Oxygen']
balmer_lines = np.array([656.3, 486.1, 434.1, 410.2,397.0])
carbon_lines = np.array([527.2,569.6,465.0,580.5,547.0,468.4])
nitrogen_lines = np.array([463.4,464.1,531.4,347.9,348.4,405.8,732.8])
helium_lines = np.array([468.6,541.2,587.6,656.0,667.8])
oxygen_lines = np.array([415.9,559.2,383.4,381.1,529.0])

# Gain locations for calibration files
#calib_path = '/usr/local/grism/grism_calibration.csv'
grism_coeffs_path = '/usr/local/grism/grism_coeffs.csv'
gain_tbl_path = '/usr/local/grism/grism_gain_table.csv'
# TEST
grism_coeffs_path = './grism_coeffs.csv'
gain_tbl_path     = './grism_gain_table.csv'


jacoby_files_path = '/usr/local/grism/Jacoby_spectra/'

# Build a dictionary of Jacoby stars for possible use in labeling spectral type
jacoby_list = '%sjacoby-list.edt' % jacoby_files_path
if os.path.isfile(jacoby_list):
	fn = open(jacoby_list,'r')
	lines = fn.readlines()
	fn.close()
	Refstar = []; Sptype = []
	for line in lines:
		refstar, sptype, lumclass = line.split()[0:3]
		sptype = '%s%s' % (sptype,lumclass)
		Refstar.append(refstar); Sptype.append(sptype)
	jacoby_dict = dict(zip(Refstar, Sptype))	

# Get command  line arguments, assign parameter values
(opts, args) = get_args()
smooth_nm = opts.Hanning
begin_wave  = opts.b; end_wave = opts.e
plt_lines = [opts.B, opts.C, opts.E, opts.N, opts.O]
cal_table = opts.cal_table
coeffs_table = opts.coeffs_table
gain_curve = opts.gain
plot_title = opts.title
large_font = opts.large_font
output_plot_name = opts.outfile
grism_image = args[0]
x0_off, y0_off  = [float(x) for x in opts.tweak.split(',')]

# Get plot options, override bogus plot format specification
plot_option = opts.plot
plot_formats = ['png','pdf']
plot_format = plot_formats[int(opts.plot_format)]

# Adjust font sizes if for publication
if large_font:
	# Set matplotlib parameters  for publication
	params = { \
	'lines.linewidth': 2.0, 'axes.linewidth': 2.0, 'axes.labelsize': 18, 'text.fontsize': 20,\
   	'legend.fontsize': 14, 'xtick.labelsize': 16, 'ytick.labelsize': 16, 'text.usetex': False,\
   	'figure.figsize': [10, 10] }
	rcParams.update(params)
else:
	params = {\
   	'lines.linewidth': 1.5, 'axes.linewidth': 1.5, 'axes.labelsize': 16, 'text.fontsize': 12,\
   	'legend.fontsize': 10, 'xtick.labelsize': 12, 'ytick.labelsize': 12, 'text.usetex': False, \
   	'figure.figsize': [4.5, 4.5] }
	rcParams.update(params)

yscale = [float(x) for x in opts.yminmax.split(',')]
verbose = opts.verbose
ref_spectrum_file = opts.ref_spec
redshift = opts.redshift
spec_width =opts.width
balmer_lines = balmer_lines*(1. + redshift)


# Read gain file, create gain table
if os.path.isfile(cal_table):
	fn = open(cal_table,'r')
	lines = fn.readlines()
	fn.close()
	wave_cal = []; gain_cal = []
	for line in lines:
		wave, gain = [float(x) for x in line.split()]
		wave_cal.append(wave); gain_cal.append(gain)
	gain_table = np.array((wave_cal, gain_cal))
else:
	sys.exit('Error: calibration file %s not found, exiting' % cal_table)

# Generate list of grism image names
Grism_names = []
if grism_image == '':
	Grism_names = glob.glob('*6*.fts')
else:
	Grism_names.append(grism_image)
if verbose: print 'Analysing file list: %s' % Grism_names

# Spin through file pairs, creating gain tables and plots
Gain = []; Object = []
for j in range(len(Grism_names)):
	gname = Grism_names[j]
	
	# Get some useful header stuff
	object, nbin, date, ut, ra, dec, exptime, filter, z = get_hdr_info(gname)
	im,hdr = fits.getdata(gname,0,header=True)
	
	# get calibration coefficients for this filter
	if os.path.isfile(coeffs_table):
		grism_angle, y0, a_coeffs, b_coeffs = get_calib_coeffs(filter, coeffs_table)
	else:
		sys.exit('Coefficients file %s not found, exiting' % coeffs_table)
	# Get reference spectrum if it exists
	jacoby_ref_file = '%s%s-Jacoby-spec.csv'  % (jacoby_files_path, object)
	if os.path.isfile(ref_spectrum_file): 
		ref_spec = get_refspec(ref_spectrum_file)
	elif os.path.isfile(jacoby_ref_file):
		ref_spec = get_refspec(jacoby_ref_file)
		ref_spec_file  = jacoby_ref_file
	else: 
		ref_spec = []; ref_spec_file = ''
	if verbose:  print 'Calibrating %s, image: %s,  ref: %s' % (object, gname, os.path.basename(ref_spec_file))
	# Star position is fixed in flipped, rotated image (assumes perfect pointing)
	x0 = 0
	x0 += x0_off; y0 += y0_off
	if verbose and opts.tweak != '0,0': print 'Adjusted star position by (%.1f,%.1f) pixels' % (x0_off,y0_off)

	# Read Grism image, flip and rotate
	im,hdr = fits.getdata(gname,0,header=True)
	im = rotate(im, -grism_angle,reshape=False)

	# Define subimage containing dispersed spectrum,
	begin_pixel = f_pixel(wmin, b_coeffs, nbin) + x0 ; end_pixel = f_pixel(wmax, b_coeffs, nbin) + x0
	xmin = int(begin_pixel  )   ; xmax = int(end_pixel )
	ymin = y0 - width/2. ; ymax = y0 + width/2.
	# Create strip spectrum subimage
	w = spec_width/float(nbin)
	ymin = int(y0-w); ymax = int(y0+w)
	subim = im[ymin:ymax,xmin:xmax]

	# Get raw (uncalibrated) spectrum by finding max (or sum?) on y-axis in strip subimage 
	spec_raw = np.array(np.mean(subim, axis=0)) * 1.0

	# Subtract smoothed off spectrum
	yoff = 100/nbin; nsmooth = 30
	ymin += yoff; ymax += yoff
	spec_off = np.array(np.median(im[ymin:ymax,xmin:xmax], axis=0))
	spec_off = smooth(spec_off, window_len=nsmooth, window='hanning')[nsmooth/2-1:-nsmooth/2]
	spec_raw -= spec_off; spec_raw /= max(spec_raw)
	npts = len(spec_raw )

	# Calculate wavelength array 
	wave_raw = np.array([f_lambda(n + begin_pixel - x0, a_coeffs, nbin) for n in range(npts)])
	
	# Interpolate raw spectrum so that the min,max wavelength and wavelength spacing matches gain table
	raw_spec = (wave_raw,spec_raw)
	interp_spec =  interp_spectrum(raw_spec, gain_table)
	wave = interp_spec[0]; amp = interp_spec[1]
	interp_spec = (wave, amp)

	# Calibrate interpolated spectrum
	cal_amp = gain_table[1] * amp
	cal_amp /= np.max(cal_amp)
	delta_nm = wave[1] -wave[0]

	# Optionally smooth calibrated spectrum   
	nsmooth = smooth_nm/delta_nm  # smoothing in pixel units
	if nsmooth > 2.0:
		cal_amp = smooth(cal_amp, window_len=nsmooth, window='hanning')
		cal_amp = cal_amp[int(nsmooth/2-1):int(-nsmooth/2)]
		cal_amp = cal_amp[0:len(wave-1)]
	cal_spec = (wave, cal_amp)

	# Plot section
	do_strip = plot_option == 1
	if object in jacoby_dict:
		sptype = jacoby_dict[object]
	else:
		sptype = ''

	# Interpolate ref_spec spectrum so that the min,max wavelength and wavelength spacing matches gain table

	if ref_spec != []:
		interp_ref_spec =  interp_spectrum(ref_spec, gain_table)
		wave_ref = interp_ref_spec[0]; amp_ref = interp_ref_spec[1]
		interp_ref_spec = (wave_ref, amp_ref)
	
	# this section generates a new gain table if needed
	if gain_curve:
		if ref_spec == []:
			print 'Cannot generate new gain curve, no reference spectrum given'
			continue
		gain_amp = np.array(interp_ref_spec[1])/np.array(interp_spec[1])
		gain_amp = medfilt(gain_amp,kernel_size=21)
		window_length = 71
		w2 = int(window_length/2)
		gain_amp = smooth(gain_amp,window_length,window='hanning')
		gain_amp = gain_amp[w2:-w2]
		gain_amp = medfilt(gain_amp,kernel_size=101)
		# Create wavelength table paired to gain table
		wave = np.array(interp_spec[0])
		cal_amp = gain_amp*np.array(interp_spec[1])
		cal_spec = (wave,cal_amp)
		gain_table = (wave,gain_amp)
		gain_curve_table = 'new_grism_gain_table.csv'
		cf = open(gain_curve_table,'w')
		for j in range(len(wave)):
			cf.write('%.1f %.2f\n' % (wave[j],gain_amp[j]) )
		print 'Created new gain curve table %s' % gain_curve_table
		cf.close
		
	if plot_title =='':
		title = 'Gemini GRISM %s %s [%s, %s] %s, %s UT, %.0f sec, Z %.1f bin %i  smoothing = %.1f nm' % \
		(object, sptype, ra[0:-1], dec[0:-3], date, ut, exptime, z, nbin, smooth_nm)
	else:
		title = plot_title
	
	plt_filename = '%s_%s_%s' % (object.replace(' ',''),date,ut.replace(':','')[0:-2]) if output_plot_name == '' else output_plot_name
	if plot_option <= 1: 
		plt_filename = '%s.%s' % (plt_filename,plot_format) 
		plot_spec(object, smooth_nm, cal_spec, subim, do_strip, plt_lines, redshift, begin_wave, end_wave, yscale, title, plt_filename)
	
	if plot_option == 2:
		if  ref_spec == []:
			sys.exit('No reference spectrum found for plot option 2, exiting')
		else:
			plt_filename = '%s-2x2.%s' % (plt_filename,plot_format)
			plot_all(object, smooth_nm, interp_spec, cal_spec, ref_spec, ref_spec_file, plt_lines, redshift,  gain_table, begin_wave, end_wave, yscale, title, plt_filename)

print 'Done'

