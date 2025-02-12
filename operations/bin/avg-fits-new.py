#!/usr/bin/env python

'''
avg-fits: Median or arithmetic average a set of FITS images using pyFITS

Input files can be wildcarded
Output is 16-bit for compatibility with Talon software

RLM 2 Nov 2013
'''

# import needed modules
import sys, getopt, glob
import numpy as np
import astropy.io.fits as pyfits

def check_parms(mode,subfile, outfile,fnames):
    if not (mode == 0 or mode == 1):
        print('Sorry, mode must be 0 or 1, quitting')
        sys.exit(1)
    elif (outfile == ''): 
        print('Sorry,  you must specify outfile name, quitting')
        sys.exit(1)	
    elif len(fnames) < 3 and mode == 0:
        print('Sorry, median requires at least 3 input images, quitting')
        sys.exit(1)
    elif(len(fnames) == 0):
        print('Sorry, no input files specified, quitting')
        sys.exit(1)
    elif subfile != None: 
        subfile_hdr = pyfits.open(subfile)
        print('Subtraction image exposure time: %.2f seconds' % subfile_hdr[0].header['EXPTIME'])
        for fname in fnames:
            fname_hdr = pyfits.open(fname)
            if (subfile_hdr[0].header['EXPTIME'] != fname_hdr[0].header['EXPTIME']):
                print('WARNING: Subtraction file has differing exposure time to file %s' % fname)
        
def usage(ustr):
    print(ustr)
    sys.exit(1)
    
def help_usage(ustr):
    print('Avg-fits calculates a mean or median output image given a set of input FITS images')
    print(ustr)
    sys.exit(1)
    
def getargs():
    ''' retrieves filenames and optional arguments from command line'''
    ustr = 'Usage: avg-fits [-m 0=median, 1=mean] [-s = subtraction_filename] [-v = verbose] [-h = help] -o outfile file1 file2 file3 ...'
    try:
        opts, fnames = getopt.getopt(sys.argv[1:], "o:m:s:vh", ["output=","mode=", "subtract=", "verbose", "help"])

        if len(fnames) == 1: fnames = glob.glob(fnames[0])
        
    except getopt.GetoptError as err:
        print(str(err)) # Prints  "option -a not recognized"
        usage(ustr)
    subfile = None; outfile = None; verbose = False
    mode = 0    # default to median average
    for opt in opts:
        if opt[0] in ('-v','--verbose'):
            verbose = True
        elif opt[0] in ('-m','--mode'):
            mode = int(opt[1])
        elif opt[0] in ('-s', '--subtract'):
            subfile = opt[1]
        elif opt[0] in ("-h", "--help"):
            help_usage(ustr)
        elif opt[0] in ("-o", "--output"):
            outfile = opt[1]
    return verbose,mode,subfile,outfile,fnames
    
# MAIN    

# Get commandline parameters
verbose, mode, subfile, outfile, fnames = getargs()

# Sanity check of input params 
check_parms(mode, subfile, outfile,fnames)

# Generate  2-d array of images, normalized to unity (assumes equal exptimes)
if verbose: print('Calculating array average...')
Im = []; Im_median = []
for fname in fnames:
	im = pyfits.getdata(fname); im_median = np.median(im)
	im = im / im_median  # Normalize each image before averaging [important for flats with varying intensity]
	Im.append(im); Im_median.append(im_median)

im_array = np.array(Im); im_median = np.median(Im_median)
if verbose: print('Median = %5.1f ADU' % im_median)

# Calculate average image (numpy array => pixel by pixel average), normalize to median of all images
if mode == 0 :
	if verbose: print('Calculating median image')
	im_avg = np.median(im_array,axis =0) * im_median
elif mode == 1:
	if verbose: print('Calculating mean image')
	im_avg = np.mean(im_array,axis=0) * im_median
else:
	sys.exit('Bad mode value %i, quitting' % mode)

# If requested, subtract an image (typically a dark) from the median image
if subfile != None:
    subim = pyfits.getdata(subfile)
    print('Subtraction image median: %5.1f ADU' % np.median(subim))
    im_avg = im_avg - subim
    print('Final image median: %5.1f ADU' % np.median(im_avg))

# Write new FITS image 
newhdr = pyfits.getheader(fnames[0])  # Use  header from first image
if (mode == 0):
    str1 = 'Mean of %i images' % len(fnames)
elif mode == 1:
    str1 = 'Median of %i images' % len(fnames)
newhdr.add_comment(str1)
hdu = pyfits.PrimaryHDU(im_avg,newhdr)
# Convert to 16-bit for Talon (camera,etc)
hdu.scale('int16','',bzero=32768)
# write FITS file
hdulist = pyfits.HDUList([hdu])
if verbose: print('writing %s' % (outfile))
hdulist.writeto(outfile, overwrite=True, output_verify='ignore')
hdulist.close()

