#!/usr/bin/env python
""" 
    Pipestep FluxCalSex

    This module defines the pipeline step to flux calibrate data files.
    The pipe step runs sextractor on the data and compares itentified
    sources with values from the StSci guide star catalog.
    
    Requirements: This step requires the source extractor program see
        https://www.astromatic.net/software/sextractor
      for details.
    
    Author: Amanda Pagul / Marc Berthoud
    
    export PYTHONPATH=/Users/berthoud/edu/outreach/Telescopes/pipeline/source
    
    2DO:
    - Init
    - Setup - determine parameters
    - Run:
      - sextractor
      - get database
      - fit
      - add keywords
      - put results in table (optional)
"""
import os # os library
import sys # sys library
import numpy as np # numpy library
import scipy # scipy library
import string # string library
import logging # logging object library
import subprocess # running a subprocess library
import requests # http request library
import astropy.table # Read astropy tables
from astropy.coordinates import SkyCoord # To make RA/Dec as float
from astropy import units as u # To help with SkyCoord
from lmfit import minimize, Parameters # For brightness correction fit
from drp.pipedata import PipeData # pipeline data object
from drp.stepparent import StepParent # pipestep stepparent object

class StepFluxCalSex(StepParent):
    """ Pipeline Step Object to calibrate Bias/Dark/Flat files
    """
    
    stepver = '0.1' # pipe step version
    
        
    def setup(self):
        """ ### Names and Parameters need to be Set Here ###
            Sets the internal names for the function and for saved files.
            Defines the input parameters for the current pipe step.
            The parameters are stored in a list containing the following
            information:
            - name: The name for the parameter. This name is used when
                    calling the pipe step from command line or python shell.
                    It is also used to identify the parameter in the pipeline
                    configuration file.
            - default: A default value for the parameter. If nothing, set
                       '' for strings, 0 for integers and 0.0 for floats
            - help: A short description of the parameter.
        """
        ### Set Names
        # Name of the pipeline reduction step
        self.name='fluxcalsex'
        # Shortcut for pipeline reduction step and identifier for
        # saved file names.
        self.procname = 'FCAL'
        # Set Logger for this pipe step
        self.log = logging.getLogger('pipe.step.%s' % self.name)
        ### Set Parameter list
        # Clear Parameter list
        self.paramlist = []
        # Append parameters
        self.paramlist.append(['sx_cmd', 'sex %s',
                               'Command to call source extractor, should contain ' +
                               '1 string placeholder for intput filepathname'])
        self.paramlist.append(['sx_options','',
                               'Command line options for source extractor ' +
                               '(This step overwrites the -c CATALOG_NAME PARAMETERS_NAME and ' + 
                               'FILTER_NAME )'])
        self.paramlist.append(['sx_confilename','psf.sex',
                               'Filepathname for SourceExtractor configuration file'])
        self.paramlist.append(['sx_paramfilename','default.param',
                               'Filepathname for SourceExtractor parameter list file'])
        self.paramlist.append(['sx_filterfilename','default.conv',
                               'Filepathname for SourceExtractor filter file'])
        self.paramlist.append(['verbose',False,
                               'Flag to log full source extractor output at DEBUG level'])
        self.paramlist.append(['delete_cat',False,
                               'Flag to delete catalog file generated by ' +
                               'source extractor'])
        self.paramlist.append(['zeropercent', 30.0,
                               'Percentile for BZERO value'])
        # confirm end of setup
        self.log.debug('Setup: done')
   
    def run(self):
        """ Runs the calibrating algorithm. The calibrated data is
            returned in self.dataout
        """
        ### Preparation
        binning = self.datain.getheadval('XBIN')
        ### Run Source Extractor
        # Make sure input data exists as file
        if not os.path.exists(self.datain.filename) :
            self.datain.save()
        # Make catalog filename
        catfilename = self.datain.filenamebegin
        if catfilename[-1] in '._-': catfilename += 'sex_cat.fits'
        else: catfilename += '.sex_cat.fits'
        self.log.debug('Sextractor catalog filename = %s' % catfilename)
        # Make command string
        command = self.getarg('sx_cmd') % (self.datain.filename)
        command += ' ' + self.getarg('sx_options')
        command += ' -c ' + os.path.expandvars(self.getarg('sx_confilename'))
        command += ' -CATALOG_NAME ' + catfilename
        command += ' -PARAMETERS_NAME ' + os.path.expandvars(self.getarg('sx_paramfilename'))
        command += ' -FILTER_NAME ' + os.path.expandvars(self.getarg('sx_filterfilename'))
        # Call process
        self.log.debug('running command = %s' % command)
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        output, error = process.communicate()
        if self.getarg('verbose'):
            self.log.debug(output)
        #subprocess.check_call(command)
        ### Extract catalog from source extractor and clean up dataset
        # Use catalog from sourse extrator (test.cat) 
        seo_catalog = astropy.table.Table.read(catfilename, format="fits", hdu='LDAC_OBJECTS')
        seo_Mag = -2.5*np.log10(seo_catalog['FLUX_AUTO'])
        seo_MagErr = (2.5/np.log(10)*seo_catalog['FLUXERR_AUTO']/seo_catalog['FLUX_AUTO'])
        # Select only the stars in the image: circular image and S/N > 10
        elongation = (seo_catalog['FLUX_APER']-seo_catalog['FLUX_AUTO'])<250 
        seo_SN = ((seo_catalog['FLUX_AUTO']/seo_catalog['FLUXERR_AUTO'])>10)
        seo_SN = (seo_SN) & (elongation) & ((seo_catalog['FLUX_AUTO']/seo_catalog['FLUXERR_AUTO'])<1000)
        self.log.debug('Selected %d stars from Source Extrator catalog' % np.count_nonzero(seo_SN))
        # Delete source extractor catalog is needed
        if self.getarg('delete_cat'):
            os.remove(catfilename)
        ### Querry and extract data from Guide Star Catalog
        # Get RA / Dec
        ra_center =  self.datain.getheadval('RA' ).split(':')
        dec_center = self.datain.getheadval('DEC').split(':')
        ra_cent =  string.join([str(s) for s in ra_center],  ' ')
        dec_cent = string.join([str(s) for s in dec_center], ' ')
        center_coordinates = SkyCoord(ra_cent + ' ' + dec_cent, unit=(u.hourangle, u.deg) )
        self.log.debug('Using RA/Dec = %s / %s' % (center_coordinates.ra, center_coordinates.dec) )
        # Querry guide star catalog2 with center coordinates 
        gsc2_query = 'http://gsss.stsci.edu/webservices/vo/CatalogSearch.aspx?'
        gsc2_query += 'RA='+str(center_coordinates.ra.value)
        gsc2_query += '&DEC='+str(center_coordinates.dec.value)
        gsc2_query += '&DSN=+&FORMAT=CSV&CAT=GSC241&SR=0.5&'
        self.log.debug('Running URL = %s' % gsc2_query)
        gsc2_result = requests.get(gsc2_query)
        # Get data from result
        filter_name = self.datain.getheadval('FILTER').split('-')[0]
        query_table = astropy.io.ascii.read(gsc2_result.text)
        table_filter = 'SDSS'+filter_name+'Mag'
        table_filter_err = 'SDSS'+filter_name+'MagErr'
        GSC_RA = query_table['ra'][(query_table[table_filter]<22) & (query_table[table_filter]>0)]
        GSC_DEC = query_table['dec'][(query_table[table_filter]<22) & (query_table[table_filter]>0)]
        GSC_Mag = query_table[table_filter][(query_table[table_filter]<22) & (query_table[table_filter]>0)]
        GSC_MagErr = query_table[table_filter_err][(query_table[table_filter]<22) & (query_table[table_filter]>0)]
        self.log.debug('Received %d entries from Guide Star Catalog' % len(GSC_RA))
        ### Mach Guide Star Catalog data with data from Source Extractor
        # Do the matching
        seo_catalog = SkyCoord(ra=seo_catalog['ALPHA_J2000'], dec=seo_catalog['DELTA_J2000'])
        GSC_catalog = SkyCoord(ra=GSC_RA*u.deg, dec=GSC_DEC*u.deg)
        idx, d2d, d3d = GSC_catalog.match_to_catalog_sky(seo_catalog[seo_SN])
        # only select objects less than 0.025 away in distance, get distance value
        mask = d2d[d2d.value<0.025]
        dist_value = 1*0.76*binning/3600. #Maximum distance is 1 pixel
        self.log.debug('Distance_Value = %f' % dist_value)
        ### Calculate the fit correction between the guide star and the extracted values
        nll = lambda *args: -residual(*args)
        eps_data = np.sqrt(GSC_MagErr[d2d.value<dist_value]**2+seo_MagErr[seo_SN][idx][d2d.value<dist_value]**2)
        result = scipy.optimize.minimize(nll, [1, -2], args=(GSC_Mag[d2d.value<dist_value], seo_Mag[seo_SN][idx][d2d.value<dist_value], eps_data))
        m_ml, b_ml = result["x"]
        self.log.info('Fitted offset is %f mag' % b_ml)
        ### Make output data 
        # Copy data from datain
        self.dataout = self.datain
        # Add Photometric Zero point magnitude
        self.dataout.setheadval('PHOTZP', -b_ml, 'Photometric zeropoint MAG=-2.5*log(data)+PHOTZP')
        self.dataout.setheadval('PHOTZPER', 0.0, 'Uncertainty of the photometric zeropoint')
        # Add Bzero and Bscale
        bzero = np.nanpercentile(self.dataout.image,self.getarg('zeropercent'))
        #-- Alternative bzero idea:
        #-mask = image_array < np.percentile(image,90)
        #-bzero = np.median(image_array[mask])
        bscale = 3631. * 10 ** (b_ml/2.5)
        self.dataout.image = bscale * (self.dataout.image - bzero)
        #print(bzero,bscale)
        #print(self.dataout.header['BZERO'])
        #self.dataout.setheadval('BZERO', bzero, 'Zero flux level - added by fluxcalsex')
        #self.dataout.setheadval('BSCALE', bscale, 'Scale from counts to Jy - added by fluxcalsex')
        #print(self.dataout.header['BZERO'])
        
def residual(params, x, data, errors):
    """ Fitting function for lmfit
    """
    m,c = params
    model = m*x+c
    inv_sigma2 = 1.0/(errors**2)
    return -0.5*(np.sum(((data-model)**2)*inv_sigma2))


if __name__ == '__main__':
    """ Main function to run the pipe step from command line on a file.
        Command:
        python stepparent.py input.fits -arg1 -arg2 . . .
        Standard arguments:
        --config=ConfigFilePathName.txt : name of the configuration file
        --test : runs the functionality test i.e. pipestep.test()
        --loglevel=LEVEL : configures the logging output for a particular level
    """
    StepFluxCalSex().execute()
    
'''HISTORY:
2018-09-019 - Started based on Amanda's code. - Marc Berthoud
'''
