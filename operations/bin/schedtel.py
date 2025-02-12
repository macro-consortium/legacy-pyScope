#!/usr/bin/env python

'''
Generate telrun.sls for current night by reading ordered list of .sch files, parsing, 
and inserting into night's schedule, selecting time slot by minimizing airmass

    - ignores lststart, lstdelta, RAOffset, DecOffset, comment keywords
    - Ignores block, blockrepeat keywords
    - ignores priority keyword - this is effectively replaced by 'first come, first served' ordered .sch lists
     -ignores binning, subimaging
    - uses only airmass minimization to select time slots
    - does not support minor planet coord lookup
    - For multiple filters, must list separate durations for each filter [i.e. nr. filters must equal nr. durations]
    - v. 0.11 account for whether observer is running the program before or after UT midnight, so ep.now gets jd correct
    - v. 0.12 add sson_code so multiple schedules for SSON are assigned sequential scan indices; added gantt-style time allocation plot
    - v. 0.20 add airmass-coded colors to LST plot, add -t option 
    - v. 0.30 add catalog lookup for objects with no specified RA/DEC [support for planets, comets, asteroids, and Simbad name lookup]; add summary stats 
    - v  0.40 add comment [mostly to support lunar tracking]
    - v  0.50 add utstart, lststart keywords (N.B. these do *not* inherit from previous scan)
    - v  0.51 Change cadence to 30 sec
    - v  0.52 Change permissions to 666 on log file
    - v. 0.60 Fix nasty bug that expanded repeat keyword incorrectly (cloned all instances, so modifying and element changed all scans)
    - v. 0.70 make plot optional by adding a -p switch
    - v. 0.80 Add support for echelle spectrometer observations
    - v. 0.90 Switch camera from CG42 to SBIG 6303 (2x2 binning, 3072x2047)
    - v. 0.91 Set plot LST limits to 0-24 to avoid problem with plot spanning 0 LST
    - v. 1.00 Add cadence keyword
    - v. 1.01 [15 Oct 18] Change to IKON 936 format (1x1 binning, 2048x2048)
    - v. 1.02 [17 Nov 18] Change parsing for comment keyword (was com, changed to comment). This should fix SSON comment scheme
    - v. 1.2  [29 Nov 2019] Fix ephem coord error: was returning EOD (ra,dec) not J2000 (a_ra, a_dec)
    - v. 1.21 [29 Jan 2020] ignore grism requests (line 290, temporary until we get focus problem fixed)
    - v. 1.22 [ 5 Feb 2020] add matplotlib.use('Agg') to allow use when su-ed to talon with no X
    - v. 1.23 [5 Feb 2020] add itemgetter so sorted works in Python 3 [line 639]
    - v. 1.24 [26 Feb 2020] switched back to SBIG format (1x1 binning, 3027x2047)/commented out grism skipping.
    - v. 1.30 [15 Mar 2020] (Ides of March!) re-apply ignore grism,
    - v. 1.31 [16 Mar 2020] replace backtick with righttick (single quote)
    - v. 1.32 [31 Mar 2020] Finally fix fancy quote marks problem (convert them to single quotes)
    - v. 1.40 [12 May 2020] add support for non-sidereal tracking
    - v. 1.50 [22 Oct 2021] add support for cmosmode keyword
    - v. 1.51 [03 Nov 2021] change time_slice from 30 sec to 10 sec
    - v. 1.6  [07 Dec 2021] add support for binning, subframes; added graceful exit if Simbad lookup fails.
    - v. 1.61 [22 Dec 2021] change default cmosmode to 3 (StackPro) [was 1] ; Added cmos mode and binning to summary list
'''

vers = '1.61 (22 Dec 2021)'

import ephem as ep # pyephem library
import numpy as np
from math import *
import sys, time, re, os.path, shlex, datetime, itertools
import urllib.request, urllib.parse, urllib.error, itertools
from astroquery.simbad import Simbad
from optparse import OptionParser
from operator import itemgetter
from astroquery.jplhorizons import Horizons
from astropy import units as u
from astropy.coordinates import Angle

#import matplotlib
#matplotlib.use('Agg')
#import matplotlib.pyplot as plt
#from pylab import *
#import matplotlib.cm as cm

# suppress warning message when object not found
import warnings
warnings.filterwarnings("ignore")

# default files for input/output
sched_cat    = '/usr/local/telescope/user/schedin/netin/schedule.cat'
schedtel_log = '/usr/local/telescope/archive/logs/'
telpath      = '/usr/local/telescope/archive/telrun/telrun.sls'

# Generate database lists of planets, asteroids, comets by reading current catalogs
planets =    ['moon',    'mercury',   'venus',   'mars',     'jupiter',    'saturn',    'uranus',    'neptune',    'pluto']
ep_planets = [ep.Moon(), ep.Mercury(), ep.Venus(), ep.Mars(), ep.Jupiter(), ep.Saturn(), ep.Uranus(), ep.Neptune(), ep.Pluto()]
asteroid_cat = '/usr/local/telescope/archive/catalogs/asteroids.edb'
asteroid_dim_cat = '/usr/local/telescope/archive/catalogs/asteroids_dim.edb'
comet_cat = '/usr/local/telescope/archive/catalogs/comets.edb'
if not os.path.isfile(asteroid_cat): sys.exit('Sorry, %s does not exist on this computer, quitting' % asteroid_cat)
asteroid_file = open(asteroid_cat,'r',encoding = 'utf-8',errors='ignore')
asteroid_dim_file = open(asteroid_dim_cat,'r',encoding='utf-8',errors='ignore')
comet_file     = open(comet_cat,'r',encoding='utf-8',errors='ignore')
ep_asteroids = [line for line in asteroid_file.readlines() if not line.startswith('#')]
ep_asteroids_dim = [line for line in asteroid_dim_file.readlines() if not line.startswith('#')]
ep_comets =   [line for line in comet_file.readlines() if not line.startswith('#')]
asteroid_names = [a.split(',')[0] for a in ep_asteroids]; a_lower = [s.lower() for s in asteroid_names]
asteroid_dim_names = [a.split(',')[0] for a in ep_asteroids_dim]; adim_lower = [s.lower() for s in asteroid_dim_names]
comet_names = [c.split(',')[0] for c in ep_comets]; c_lower = [s.lower() for s in comet_names]


usage = 'Usage: schedtel [-options]. Create a telrun.sls file for tonight'
def get_args():
    parser = OptionParser(description='Program %prog. Creates a telescope schedule file [telrun.sls]',version = vers, usage=usage)
    parser.add_option('-f', dest = 'schedcat', metavar = 'Schedule catalog', action ='store', default = sched_cat, help = 'Priority-ordered catalog containing list of .sch files')
    parser.add_option('-e', dest = 'elmin', metavar='Min. Elevation', action = 'store', default =15,  type = float,help = 'Minimum elevation [deg]')
    parser.add_option('-p', dest = 'plot', metavar='Plot', action = 'store_true', default = False, help = 'Plot timeline, default False')
    parser.add_option('-t', dest = 'telrun', metavar='Telrun write', action = 'store_true', default = False, help = 'Write telrun.sls to archive/telrun, default: False') 
    parser.add_option('-v', dest = 'verbose', metavar='Verbose', action = 'store_true', default = False, help = 'Verbose output, default False')
    parser.add_option('-n', dest = 'nowstart', metavar='Nowstart', action = 'store_true', default = False, help = 'Start schedule now (use if scheduling after dusk)')
    return parser.parse_args()

def hms2hr(hms_str):
    import re
    result = 0
    fields = re.split(r'[: _]', hms_str)
    fields = [float(x) for x in fields]
    while len(fields) > 0:
        result = result/60.0 + fields.pop()
    return result

def hr2hms(hr):
    dhrs = np.mod(hr,24)
    hmshrs = floor(dhrs)
    hmsmin = floor((dhrs-hmshrs)*60.)
    hmssec = ((dhrs-hmshrs)*60.-hmsmin)*60.
    return "%02d:%02d:%02d" % (hmshrs, hmsmin, hmssec)

def get_times(t):
    observatory.date = t
    y,m,d =  t.triple()
    # Fractional hr
    ut_hr =  (d % 1) * 24.
    local_hr = float(observatory.date + utdiff*ep.hour) * 12./np.pi
    lst_hr   = float(observatory.sidereal_time()      ) * 12./np.pi
    
    # Format in hh:mm:ss
    local_hms = str(ep.Date(observatory.date + utdiff*ep.hour)).split()[1][0:8]
    ut_hms    = str(observatory.date                          ).split()[1][0:8]
    hh,mm,ss =  str(observatory.sidereal_time()               ).split(':')
    ss = ss[0:2]
    if len(hh) == 1: hh = '0' + hh
    lst_hms = hh + ':' + mm + ':' + ss
    return local_hr, ut_hr, lst_hr, local_hms, ut_hms, lst_hms


def deg2sex(eph):
    # Extract ICRF coords, rate from JPL Horizons ephemerides object
    ra = Angle(np.array(eph['RA'])[0], u.degree)
    ra_str = ra.to_string(unit=u.hour, sep=':',precision=2)
    dec = Angle(np.array(eph['DEC'])[0], u.degree)
    dec_str = dec.to_string(unit=u.degree, sep=':',precision =1)
    ra_rate = np.array(eph['RA_rate'].to('arcsec/s'))[0]
    dec_rate = np.array(eph['DEC_rate'].to('arcsec/s'))[0]
    return ra_str,dec_str, ra_rate, dec_rate

def get_JPL_object(name):
    global jd_ep
    jd = jd_ep + 2415020 # Offset in ephem
    obj = Horizons(id=name,location='857', id_type = 'smallbody', epochs=jd)
    try:
        eph = obj.ephemerides()
        ra_str, dec_str, ra_rate,dec_rate = deg2sex(eph)
        return [True,ra_str, dec_str, ra_rate, dec_rate]
    except:
        return [False]

def get_object_coords(objname):
    global observatory, planets, ep_planets, ep_asteroids, ep_comets, a_lower, adim_lower, c_lower
    success = True; fixed = False
    name = objname.lower()

    # Planet or moon?  
    if any([name == planet for planet in planets]):
        i = planets.index(name)
        obj = ep_planets[i]
        obj.compute(observatory)
        ra_str = obj.a_ra; dec_str = obj.a_dec
        edb = '%s,f|M|x,%s,%s,0.0,2000' % (objname,ra_str,dec_str)
    # Asteroid?
    elif any([name == asteroid_name for asteroid_name in a_lower]):   
        i = a_lower.index(name)
        obj = ep.readdb(ep_asteroids[i])
        obj.compute(observatory)
        ra_str= obj.a_ra; dec_str = obj.a_dec
        edb = obj.writedb()
    # Dim asteroid?
    elif any([name == asteroid_name for asteroid_name  in adim_lower]):
        i = adim_lower.index(name)
        obj = ep.readdb(ep_asteroids_dim[i])
        obj.compute(observatory)
        ra_str= obj.a_ra; dec_str = obj.a_dec
        edb = obj.writedb() 
    # Comet?
    elif any([name == comet_name for comet_name in c_lower]): 
        i = c_lower.index(name)
        obj = ep.readdb(ep_comets[i])
        obj.compute(observatory)
        ra_str = obj.a_ra; dec_str = obj.a_dec
        edb = obj.writedb()
    # Try JPL Horizons
    elif(get_JPL_object(objname)[0]):
        success, ra_str, dec_str, ra_rate,dec_rate = get_JPL_object(objname)
        edb = '%s,f|M|x,%s,%s,0.0,2000' % (objname,ra_str,dec_str)
        fixed = True
    # Simbad object?
    else:
        try:
            objtable = Simbad.query_object(name)
            ra_str  = str(objtable['RA'][0])
            dec_str = str(objtable['DEC'][0])
            edb = '%s,f|M|x,%s,%s,0.0,2000' % (objname,ra_str,dec_str)
            fixed = True
        except:
            success = False
            ra_str = ''; dec_str = ''; edb = ''         
    return success, fixed, str(ra_str), str(dec_str),str(edb) 

def get_index(mylist, substr):
    # Return index of (first) list element containing substr
    for i in range(len(mylist)):
        if mylist[i].lower().startswith(substr.lower()):
            return i
    return -1 

def get_keyvalue(keyword, scan):
    # Given keyword, return keyvalue
    keyvalue = None
    i = get_index(scan, keyword)
    if i != -1:
        return scan[i+1]
    else:
        return None

def set_keyvalue(keyword, new_value, scan):
    # Given keyword, return keyvalue
    keyvalue = None
    i = get_index(scan, keyword)
    if i != -1:
        success = True
        scan[i+1] = new_value
    else:
        success = False
    return success, scan

def mk_scan_dict(scan, previous_scan_dict):
    ''' make a scan dictionary containing observing params, inheriting values from previous scan '''
    x =[(scan[2*j],scan[2*j+1]) for j in range(len(scan)//2)]
    scan_dict = previous_scan_dict
    for j in range(len(x)):
        (key, val) = x[j]
        key  = key[0:min(3,len(key))]  # trim key value to match dict key
        if key in scan_dict: scan_dict[key] = val
    return scan_dict

def xparse_schfile(schfile):
    ''' 
    Read .sch file, expand repeats, multiple filters/durations, 
    and return a list containing a dictionary of observing parameters for each scan
    '''
    global default_scan_dict, sson_scans
    
    fn = open(schfile,'r')
    lines = fn.readlines()
    fn.close()
    obscode = schfile[0:3]

    # remove extraneous equal signs, quote marks, and blank lines
    Lines = []
    for line in lines:
        line = line.replace("=",' ')
        line = line.replace("‘","'")
        line = line.replace("’","'")
        s = shlex.split(line)
        if len(s) > 0: Lines.append(s)

    # Remove comment lines
    Lines2 = []
    for line in Lines:
        if line[0][0] != '!' and line[0][0] != '#': 
            Lines2.extend(line)
    
    # Divide into separate scans by searching for '/' character
    allscans = [list(x[1]) for x in itertools.groupby(Lines2, lambda x: x=='/') if not x[0]]

    # Retrieve title, observer key values from first scan
    title    = get_keyvalue('tit',allscans[0])
    observer = get_keyvalue('obs',allscans[0])

    # Eat lines with blockrepeat keyword for now
    allscans2 = []
    for scan in list(allscans):
        x = [s.upper() for s in scan] 
        if  not 'BLOCKREPEAT' in x: 
            allscans2.append(list(scan))
      
    # Expand scans with a repeat keyword, use cadence keyword if specified
    allscans3 = []
    use_cadence = False; use_ut = False ; use_lst = False
    for scan in allscans2:  
        s =  get_keyvalue('rep',scan)
        utstart =  get_keyvalue('utstart', scan)
        lststart = get_keyvalue('lststart', scan)
        if utstart != None: 
            use_ut = True
            utstart_hr = hms2hr(get_keyvalue('utstart',scan))
        if lststart != None: 
            use_lst = True
            lststart_hr = hms2hr(get_keyvalue('lststart',scan))
        
        cadence =  get_keyvalue('cad', scan)
        if cadence != None:
            use_cadence = True
            cad_time = hms2hr(cadence) 
            
        if s != None:
            repeat_count = int(s)
        else:
            repeat_count = 1
        
        for j in range(repeat_count):
            if use_cadence and use_ut:
                ut_hms = hr2hms( np.mod(utstart_hr + j*cad_time ,24.) )
                success, scan = set_keyvalue('utstart',ut_hms,scan)
            elif use_cadence and use_lst:
                lst_hms = hr2hms( np.mod(lststart_hr + j*cad_time ,24.) )
                success, scan = set_keyvalue('lststart',lst_hms, scan)
            allscans3.append(list(scan))
    
    # Convert all keywords to lower case
    allscans4 = []
    for scan in allscans3:
        for j  in range(0,len(scan),2):
            scan[j] = scan[j].lower()
        allscans4.append(list(scan))

    # Add edb keyword; look up coordinates and edb for scans with no specified ra/dec; skip scan if no coords available
    allscans5 = []

    for scan in allscans4: 
        # TEMPORARY
        filter = get_keyvalue('fil',scan)
        # if filter == '6':
        	# srcname = get_keyvalue('sou',scan)
        	# print('Warning: skipping grism filter request, source %s' % srcname)
        	# continue
        objname = get_keyvalue('sou', scan)
        if verbose: print('Catalog/Simbad object coordinate lookup: %s' % objname)
        
        # Use user-supplied coords if given
        if get_keyvalue('ra',scan) != None:
            edb_str = '%s,f,%s,%s,0.00,2000,0' % (get_keyvalue('sou',scan), get_keyvalue('ra',scan),get_keyvalue('dec',scan) )
            ra_str = get_keyvalue('ra',scan); dec_str = get_keyvalue('dec',scan)
            ra_str = ra_str.replace(' ',':',2) ; dec_str = dec_str.replace(' ',':',2)
            scan += ['ra', ra_str, 'dec', dec_str, 'edb', edb_str]
            allscans5.append(list(scan))
        
        # No coords given, so try lookup 
        else:
            success, fixed, ra_str, dec_str, edb_str = get_object_coords(objname)
            if success:
                ra_str = ra_str.replace(' ',':',2) ; dec_str = dec_str.replace(' ',':',2)
                scan += ['ra', ra_str, 'dec', dec_str, 'edb', edb_str]
                allscans5.append(list(scan))
            else:
                print('WARNING: Schedule file %s, cannot find coordinates for %s, skipping' % (schfile, objname))
        
    # Make a dictionary for each scan, add observer code keyvalue
    j = 0; S = []
    for scan in allscans5:
        if j == 0: 
            previous_scan_dict = default_scan_dict
        else:
            previous_scan_dict = scan_dict
        scan_dict =  mk_scan_dict(scan, previous_scan_dict) 
        scan_dict['comment']    = get_keyvalue('comment', scan)
        scan_dict['obscode']    = obscode
        scan_dict['lststart']   = get_keyvalue('lst', scan)
        scan_dict['utstart']    = get_keyvalue('uts', scan)
        scan_dict['cmosmode']   = get_keyvalue('cmosmode',scan)    # New October 2021
        scan_dict['binning']    = get_keyvalue('binning',scan)     # New December 2021
        scan_dict['frame_size'] = get_keyvalue('frame_size',scan) # New December 2021
        scan_dict['frame_position'] = get_keyvalue('frame_position',scan) # New December 2021
        
        if scan_dict['cmosmode']   == None : scan_dict['cmosmode'] = 3
        if scan_dict['binning']    == None : scan_dict['binning'] = '1x1'
        if scan_dict['frame_size'] == None : scan_dict['frame_size'] = '4096x4096'
        if scan_dict['frame_position'] == None : scan_dict['frame_position'] = '0+0'
        S.append(scan_dict.copy())
    
    # Insert filter, duration keywords, creating new scans if multi-valued, and inheriting from previous scan if none given
    j = 0
    for scan_dict in S:
        scan_dict = S[j]
        filters   = scan_dict['fil'].split(",")
        durations = scan_dict['dur'].split(",")
        if len(filters) != len(durations): sys.exit('Different number of filter/duration in %s, not currently supported, exiting' % schfile)
        if len(filters) == 0: continue  # inherit filter[s], duration[s] if not given
        del S[j]
        for n in range(len(filters)):
            new_dict = scan_dict.copy()
            new_dict['fil'] = filters[n]
            new_dict['dur'] = durations[n]
            S.insert(j,new_dict)        
        j += 1
    
    # add hex sequence numbers and schedule file name, keeping running sequence for SSON schedules
    for j in range(len(S)):
        if schfile[0:2] == sson_code:
            S[j]['seq'] = format(j + sson_scans,'02x')
        else:
            S[j]['seq'] = format(j,'02x')
        S[j]['schedname'] = schfile
        S[j]['tit'] = title
        S[j]['obs'] = observer
    return S

def write_telrun(allscans,telfile):
    fn = open(telfile,'w')
    keys = ['status','Start JD', 'lstdelta, mins','schedfn','title','observer','comment','EDB','RAOffset','DecOffset',\
    'frame position','frame size','binning','duration, secs','shutter','ccdcalib','filter','cmosmode','Extended action', \
    'Ext. Act. Values', 'priority','pathname'] 
    vals = [None]*22
    for scan in allscans:
        if scan['status'] == False: continue
        t = ep.Date(scan['jdstart'] - 2415020)
        jd = float(t) + 2415020
        doy = datetime.datetime.now().timetuple().tm_yday +1
        ut = str(t).split()
        ut_date_str = '%s %s' % (ut[0],ut[1])
        
        pathname = '/usr/local/telescope/user/images/%s%03d%02s.fts' % (scan['obscode'],doy,scan['seq'])   
        vals[0]  = 'N'                                                 # Status                            
        vals[1]  = '%13.5f (%s UTC)' % (jd,ut_date_str)                # JDstart (UT) 
        vals[2]  = '360'                                               # lstdelta
        vals[3]  = scan['schedname']                                   # sch file name
        vals[4]  = scan['tit']                                         # title
        vals[5]  = scan['obs']                                         # observer
        vals[6]  = scan['comment']                                     # comment
        vals[7]  = '%s' % scan['edb']                                  # object EDB string
        vals[8]  = '00:00:00.0'                                        # RA  offset
        vals[9]  = '00:00:00.0'                                        # Dec offset
        vals[10] = scan['frame_position']                              # Frame position (LL corner)
        vals[11] = scan['frame_size']                                  # Frame size
        vals[12] = scan['binning']                                     # Binning
        vals[13] = scan['dur']                                         # Duration, sec
        vals[14] = 'Open'                                              # Shutter
        vals[15] = 'CATALOG'                                           # ccdcalib
        vals[16] = scan['fil'].upper()                                 # filter
        vals[17] = scan['cmosmode']                                    # cmosmode
        vals[18] = ''                                                  # Extended action
        vals[19] = ''                                                  # Extended act. values
        vals[20] = 10                                                  # Priority (ignored)
        vals[21] = pathname                                            # Pathname
        
        for j in range(22):
            fn.write( '%2i %17s: %s\n' % ( j, keys[j], vals[j] ) )
            #print    '%2i %17s: %s' % ( j, keys[j], vals[j] )
    fn.close()
    print('Wrote: %s' % telfile)
    return

    
def jd_to_lst(mjd):
    # convert from (ephem, 1899-based) mjd to lst (frac hr)
    obs = ep.Observer()
    obs.lat  = ep.degrees(str(0.55265/deg))
    obs.long = ep.degrees(str(-1.93035/deg))
    obs.date = ep.Date(mjd-2415020)
    lst = float(obs.sidereal_time()*12/np.pi)
    return lst

def plot_scans(lst_dict, airmass_dict, date_str):
    # Plot a gantt-style graph of usage per observing code vs LST, one line per code, plus total usage
    #colors = itertools.cycle(["r", "b", "g","c","m","y"])
    plt.rcdefaults()
    ncodes = len(lst_dict)
    fig, ax = plt.subplots(figsize=(18,10))
    y_pos = np.arange(ncodes)
    j = 0
    for key in list(lst_dict.keys()): 
        obsfile = key
        x_array = lst_dict[key]
        y_array = [y_pos[j] for x in x_array]
        airmass = airmass_dict[key]
        c = ax.scatter(x_array,y_array,s = 50, marker ='s', lw=0.0, c=airmass, vmin = 1.0, vmax = 3.0, cmap=cm.brg_r)
        j += 1
    ax.set_yticks(y_pos)
    ax.set_yticklabels(list(lst_dict.keys()))
    ax.invert_yaxis()  # labels read top-to-bottom
    ax.grid(True)
    ax.set_xlabel('LST Time [hr]')
    ax.set_title('Gemini telescope schedule for %s' % date_str) 
    #ax.set_xlim(lst_slice[0],lst_slice[-1])
    ax.set_xlim(0,24)
    cbar = plt.colorbar(c)
    cbar.set_label('Airmass')
    plt.show()
    return


# ===== MAIN =======

deg = pi/180.
slice_time  = 10*ep.second

# SSON code
sson_code = '7_'

# Parse command line arguments
(opts, args) = get_args()
schedcat  = opts.schedcat
eldeg_min = opts.elmin
telrun = opts.telrun
plot = opts.plot
verbose = opts.verbose
nowstart = opts.nowstart

# Set up Winer observatory, observing limits in ephem
min_elev = '+10'        # Define minimum observable elevation in degrees
twilight_elev = '-12'  # Define solar elevation at astronomical twilight, when roof opens
observatory  = ep.Observer()
observatory.horizon = twilight_elev
# Winer observatory
observatory.lat = ep.degrees(str(0.55265/deg))
observatory.long = ep.degrees(str(-1.93035/deg))
obsname = 'Gemini Telescope, Winer Obs.'
utdiff = -7; localtimename = 'MST'

# Schedule tonight (UT) - but be careful: if it's before  midnight UT, add a day (it's the previous afternoon)
observatory.date = ep.now()
if float( '%.5f' % observatory.date) %  1 < 0.5: 
    if verbose: print('Adding a day for UT')
    observatory.date += 24*ep.hour

# Calculate JD and the date string
jd_ep = float(ep.Date(observatory.date)); jd = jd_ep + 2415020
date_str = str(observatory.date).split()[0]


# Determine dusk and dawn of upcoming night
sun = ep.Sun()
sun.compute(observatory)
dawn = ep.Date(sun.rise_time + utdiff*ep.hour)
dusk = ep.Date(sun.set_time + utdiff*ep.hour)
dawn_str = str(dawn).split()[1][0:8]; dusk_str = str(dusk).split()[1][0:8]

# Calculate local times of astronomical dusk, dawn on specified date 
local_hr, ut_hr, lst_hr, local_dawn, ut_dawn, lst_dawn = get_times(ep.Date(sun.rise_time))
local_hr, ut_hr, lst_hr, local_dusk, ut_dusk, lst_dusk = get_times(ep.Date(sun.set_time))

# If this program is run late (after dusk at Winer) and user chooses, make schedule starting at current time 
if nowstart:
    print('Starting schedule now [option -n selected], not at dusk')
    jd_start = ep.julian_date(ep.now())
else:
    jd_start = ep.julian_date(sun.set_time)
jd_stop =  ep.julian_date(sun.rise_time)
Nslice = int ( (jd_stop - jd_start)  /slice_time )
print('Nightly schedule for %s (JD %.3f - %.3f)\nSpans LST range %s - %s\nContains %i time slices, each %0.f sec'  % \
(date_str, jd_start, jd_stop, lst_dusk, lst_dawn, Nslice, slice_time/ep.second))

# Create lists of start JD, status, scan number of each time slice
homing_time = 5*ep.minute
jd_slice = [jd_start + homing_time + j*slice_time for j in range(Nslice)]
lst_slice = [jd_to_lst(x) for x in jd_slice]
status_slice  =  [0  for j in range(Nslice)]
scan_slice    =  [-1 for j in range(Nslice)]
slice_owner   =  ['' for j in range(Nslice)]
slice_airmass =  [0  for j in range(Nslice)]

# Block 2 min per hour for focus runs by setting to 1
foc_int = 1*ep.hour; foc_dur = 2*ep.minute
focus_flag  =  [ not((( jd_slice[j] - (jd_start+homing_time) )/foc_int % 1) * foc_int) < foc_dur for j in range(Nslice)]
slice_status = focus_flag

# Read in a list of .sch files and process them in order
schfiles = []
fn = open(schedcat ,'r')
lines = fn.readlines()
for line in lines:
    if line.strip() != '': schfiles.append(line.split()[0])

# Each scan request has its own dictionary with these keywords/values
default_scan_dict = {'obscode':'','jdstart':'','status':False, 'schedname':'','comment':'', 'lststart':'', 'utstart':'',\
'seq':0, 'tit':'',  'obs':'',    'pri':100, 'sou':'',  'ra':'',  'dec':'', 'edb':'', 'fil':'',\
'dur':'','airmass':0,'cmosmode':3, 'frame_position':'0+0', 'frame_size':'4096x4096','binning':'1x1'}

# Parse the sch files, filling in keyvalues for each scan dictionary
allscans = []
sson_scans = 0
for schfile in schfiles:
    # Read sch file, create list of observing parameters in dictionaries, retrieve required keywords
    scans = xparse_schfile(schfile)
    if schfile[0:2] == sson_code: 
        sson_scans += len(scans)
    allscans.extend(scans)

Nscans = len(allscans)

# Calculate the number of time slices needed for each scan, add to nslice key 
slice_tot = 0
for j  in range(Nscans):
    scan = allscans[j]
    #print(scan['dur'])
    #print(scan['obs'])
    nslice = int ((float(scan['dur'])) * ep.second / slice_time ) + 1
    if scan['fil'] == '8' or scan['fil'] == '9' :
        nslice += 1                        # Add refocussing time for grism images
    if scan['fil'].lower() == 'e':
        nslice += 2                        # Add refocussing, calibration time for echelle requests
    scan['nslice']  = nslice
    slice_tot += nslice

print('%i images requested (total time = %.1f hrs)\n' % (Nscans, slice_tot * slice_time /ep.hour))

    
# Spin through available time slots to find, for each scan request, the time closest to transit [default] or ut/lst start
for j in range(Nscans):
    scan = allscans[j]
    sou = scan['sou']
    ra  = scan['ra']
    dec = scan['dec']
    edb = scan['edb']
    # Set start_hr
    if scan['lststart']  != None:
        start_hr = hms2hr(scan['lststart'])
        schedule_type = 'lst'
    elif scan['utstart'] != None:
        start_hr = hms2hr(scan['utstart'] )
        schedule_type ='ut'
    else:
        start_hr = None
        schedule_type = ''
    object = ep.readdb(edb)
    nslice = int ((float(scan['dur'])) * ep.second / slice_time ) + 1
    eldeg_max = 0 ; kmax = 0 ; ut_diff_max =99 ; lst_diff_max = 99
    for k  in range(Nslice - nslice - 2):
        if False in slice_status[k:k+nslice]: continue  # check if time slice already taken
        t = ep.Date(jd_slice[k] - 2415020)
        observatory.date = t
        local_hr, ut_hr, lst_hr, local,ut,lst = get_times(t)
        object.compute(observatory)
        if schedule_type == 'ut':
            ut_diff = np.abs(start_hr - ut_hr)
            if ut_diff < ut_diff_max:
                kmax = k
                ut_diff_max = ut_diff
                eldeg_max = float(object.alt)/deg
        elif schedule_type == 'lst':
            lst_diff = np.abs(start_hr - lst_hr)
            if lst_diff < lst_diff_max:
                kmax = k
                lst_diff_max = lst_diff
                eldeg_max = float(object.alt)/deg
        else: 
            eldeg = float(object.alt)/deg
            if eldeg < eldeg_min: continue
            if eldeg > eldeg_max:
                kmax = k
                eldeg_max = eldeg

    if kmax != 0:   
        for k in range(kmax,kmax+nslice+1): 
            slice_status[k]  = False     # Allocate time slices for this observation
            slice_owner[k]   = scan['obscode']
            slice_airmass[k] = 1. / np.sin(eldeg_max *deg)
        scan['status'] = True
        scan['jdstart'] = jd_slice[kmax]
        allscans[j] = scan

# Generate dictionary for plotting 
lst_dict ={}; airmass_dict = {}
for schfile in schfiles:
    obscode = schfile[0:3]
    lst = []; airmass = []
    for slice in range(Nslice):
        if obscode == slice_owner[slice]: lst.append(lst_slice[slice])
        if obscode == slice_owner[slice]: airmass.append(slice_airmass[slice])
    lst_dict[obscode] = lst
    airmass_dict[obscode] = airmass
lst_total = []; airmass_total = []
for slice in range(Nslice):
    if slice_status[slice] == False: 
        lst_total.append(lst_slice[slice])
        airmass_total.append(slice_airmass[slice])
lst_dict['TOTAL']     = lst_total
airmass_dict['TOTAL'] = airmass_total

# Make a gantt-style plot of all observations for the night
if plot:
    import matplotlib
    import matplotlib.pyplot as plt
    from pylab import *
    import matplotlib.cm as cm
    
    if verbose: print('Plotting timeline...')
    plot_scans(lst_dict, airmass_dict, date_str)
    
key_order = ['status','Start JD', 'lstdelta, mins','schedfn','title','observer','comment','EDB','RAOffset','DecOffset',\
'frame position','frame size','binning','duration, secs','shutter','ccdcalib','filter','cmosmode','Extended action', \
'Ext. Act. Values', 'priority','pathname'] 

# Sort scans by jdstart
#print([x for x in allscans if x['jdstart'] == ''])
tempscans = []
for i in range(0,len(allscans)):
    if allscans[i]['jdstart'] == "":
        continue
    tempscans.append(allscans[i])
allscans = tempscans
allscans = sorted(allscans, key=itemgetter('jdstart')) 
Nscans = len(allscans)
# write summary file

list_file = '%stelrun_%s.lis' % (schedtel_log,date_str.replace('/','-'))
print('Writing summary to %s' % list_file)
fn = open(list_file,'w')
cmos_str = ['Low ','High','HDR ','Spro']
fn.write('Obscode               Object        RA  (J2000)   Dec (J2000) Fil  Dur   El     Mode Binning  Z      MST         UT        LST\n' )
fn.write('------------------------------------------------------------------------------------------------------------------------------\n')   
for j in range(Nscans):
    scan = allscans[j]
    if scan['status'] == False:
        if verbose: print('Scan %i (%s) not scheduled' % (j, scan['sou']))
    else:
        t = ep.Date(scan['jdstart'] - 2415020)
        local_hr, ut_hr, lst_hr, local,ut,lst = get_times(t)
        observatory.date = t
        sou = scan['sou']; ra  = scan['ra'][0:10]; dec = scan['dec'][0:9]; fil = scan['fil'].upper(); dur = float(scan['dur'])
        db_str = scan['edb']
        object = ep.readdb(db_str)
        object.compute(observatory)
        eldeg = float(object.alt)/deg
        airmass = 1/np.sin(eldeg*deg)
        obscode = scan['obscode']
        cmos_mode = cmos_str[int(scan['cmosmode'])]
        binning = scan['binning']	
        fn.write('%3s   %24s    %11s   %11s   %s  %5.1f   %4.1f   %4s  %3s   %4.1f   %s   %s   %s\n' % \
        (obscode, sou,   ra, dec, fil, dur, eldeg, cmos_mode, binning, airmass, local, ut, lst ) )

fn.close()

# Change permissions  on log file to group write
#os.chmod(list_file,0o666)


# Report summary statistics, fraction of all observer's requests that were scheduled
print() 
frac_night = slice_status.count(False)/ float(Nslice)
total_hr = frac_night * Nslice * slice_time * 24 
print('Total time scheduled = %.2f hr (%.1f%% of available time slots)' %  (total_hr, 100*frac_night))

for schfile in schfiles:
    obscode = schfile[0:3]
    obs_slice = 0; N_sched = 0; N_fail = 0
    for slice in range(Nslice):
        if obscode == slice_owner[slice]: obs_slice += 1
    for scan in allscans:
        if scan['obscode'] == obscode:
            if scan['status'] == True:  N_sched += 1 
            if scan['status'] == False: N_fail  += 1
    N_total = N_sched + N_fail
    print('Observer code %s scheduled time:  %.1f hr [%3i of %3i image requests]' % (obscode, obs_slice* slice_time/ep.hour, N_sched, N_total))


# Write telrun file 
if telrun:
    telfile = telpath
else:
    telfile = './telrun.sls'
try:
    write_telrun(allscans,telfile)
except:
    print('Sorry, only user talon can create telrun.sls in archive/telrun')
