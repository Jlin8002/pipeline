#!/usr/bin/env python
"""
    Pipestep SrcExtPy

    This module defines the pipeline step to extract sources from data files.
    The pipe step runs the python library SEP on the data in order to extract
    the sources and calculate a first order approximation of flux and magnitude

    For more info check out the read the docs for SEP: https://sep.readthedocs.io/

   This uses the SEP python library for source extraction.
    Author: Amanda Pagul / Marc Berthoud/ Daniel Sharkey

    Update 8/6/20 by Daniel Sharkey
    Here I have attempted to convert the original Fluxcalsex step into a 
    Sextract step that uses the python library SEP.



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
import sep # Extracts Sources and Calculates Flux
from astropy.io import fits
from astropy.io import ascii
#from astropy.coordinates import SkyCoord # To make RA/Dec as float
#from astropy import units as u # To help with SkyCoord
from astropy.stats import mad_std
#import matplotlib # to make plots
#matplotlib.use('Agg') # Set pixel image
import pylab as plt # pylab library for plotting
from lmfit import minimize, Parameters # For brightness correction fit
from darepype.drp import StepParent # pipestep stepparent object


class StepSrcExtPy(StepParent):
    """ Pipeline Step Object to extract sources from image files
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
        self.name='srcextpy'
        # Shortcut for pipeline reduction step and identifier for
        # saved file names.
        self.procname = 'SEP'
        # Set Logger for this pipe step
        self.log = logging.getLogger('pipe.step.%s' % self.name)
        ### Set Parameter list
        # Clear Parameter list
        self.paramlist = []
        # Append parameters
        self.paramlist.append(['sourcetable',False,
                               'Flag for making txt table of all sources'])
        self.paramlist.append(['sourcetableformat','csv',
                               'txt table format (see astropy.io.ascii for options)'])
        self.paramlist.append(['maskthreshold', 0.0,
                                'mask threshold for background detection'])
        self.paramlist.append(['backgroundwh', [16,16],
                                'background box width and height for background detection'])
        self.paramlist.append(['filterwh', [3,3],
                                'filter width and height for background detection'])
        self.paramlist.append(['fthreshold', 0.0,
                                'filter threshold for background detection'])
        self.paramlist.append(['extractthersh', 2.0,
                                'extraction threshold for source extration'])
        self.paramlist.append(['bfactor', 10.0,
                                'brightness factor for creating highlevel threshold'])
        self.paramlist.append(['deblend', 256,
                                'deblend threshold for source extration'])
        self.paramlist.append(['kronf', 2.5,
                                'factor multiplied into kronrad to get radius for integration'])


        # confirm end of setup
        self.log.debug('Setup: done')

    def run(self):
        """ Runs the calibrating algorithm. The calibrated data is
            returned in self.dataout
        """
        ### Preparation
        binning = self.datain.getheadval('XBIN')
        ### Perform Source Extraction
        #Open data out of fits file for use in SEP
        psimage = self.datain.image
        image = psimage.byteswap().newbyteorder()

        #These variables are used for the background analysis. 
        #We grab the values from the paramlist
        maskthresh = self.getarg('maskthreshold')
        backwh= self.getarg('backgroundwh')
        filwh= self.getarg('filterwh')
        bw, bh = backwh[0], backwh[1]
        fw, fh = filwh[0], filwh[1]
        fthresh = self.getarg('fthreshold')

        #Create the background image and it's error
        bkg = sep.Background(image, maskthresh=maskthresh,bw=bw, bh=bh, fw=fw,
        fh=fh, fthresh=fthresh) 

        bkg_image=bkg.back()

        bkg_rms =bkg.rms()
        #Subtract the background from the image
        image_sub = image - bkg_image
        #Calculate the Median and STD of the Subtracted Image
        imsubmed = np.nanmedian(image_sub)
        imsubmad = mad_std(image_sub)

		#Create variables that are used during source Extraction and Flux Calculation
        #Some defined in the param are grabbed now
        extract_thresh = self.getarg('extractthersh')
        bright_factor= self.getarg('bfactor')
        deblend_nthresh = self.getarg('deblend')
        kfactor = self.getarg('kronf')
        extract_err = bkg_rms
        #Extract sources from the subtracted image. It extracts a low threshold list and a high threshold list
        sources = sep.extract(image_sub, extract_thresh, err=extract_err, deblend_nthresh= deblend_nthresh)
        sourcesb= sep.extract(image_sub, extract_thresh*bright_factor, err=extract_err)

        ### Sort sources by descending isophotal flux. (Taken from Dr. Harper's Explore SEP Notebook)
        ind = np.argsort(sources['flux'])
        reverser = np.arange(len(ind) - 1,-1,-1)
        rev_ind = np.take_along_axis(ind, reverser, axis = 0)
        objects = np.take_along_axis(sources, rev_ind, axis = 0)

        indb = np.argsort(sourcesb['flux'])
        reverserbri = np.arange(len(indb) - 1,-1,-1)
        rev_indb = np.take_along_axis(indb, reverserbri, axis = 0)
        objectsb = np.take_along_axis(sourcesb, rev_indb, axis = 0)

        ###Do basic uncalibrated measurments of flux for use in step astrometry. 
        '''
        First we calculate flux using Ellipses. In order to do this we need to calculate
        the Kron Radius for the ellipses the Extract process identified using the ellipse 
        parameters it gives. 
        R is equal to 6 as that is the default used in Source Extractor
        '''
        kronrad, krflag = sep.kron_radius(image_sub, objects['x'], objects['y'], 
        	objects['a'], objects['b'], objects['theta'], r=6.0)

        kronradb, krflagb= sep.kron_radius(image_sub, objectsb['x'], objectsb['y'], 
            objectsb['a'],objectsb['b'], objectsb['theta'], r=6.0)

        #Using this Kron radius we calculate the flux
        #This is equivalent to FLUX_AUTO in SExtractor
        flux_elip, fluxerr_elip, flag = sep.sum_ellipse(image_sub, objects['x'], objects['y'], objects['a'], 
        objects['b'], objects['theta'], r= kfactor*kronrad, err=bkg_rms, subpix=1)
        flux_elipb, fluxerr_elipb, flag = sep.sum_ellipse(image_sub, objectsb['x'], 
        objectsb['y'], objectsb['a'], objectsb['b'], objectsb['theta'],
        r= kfactor*kronradb, err=bkg_rms, subpix=1)

        #Now we want to calculate the Half-flux Radius. This will be reported later
        #First in order to establish a zone to integrate over we need an Rmax
        dx = (objects['xmax'] - objects['xmin']) / 2
        dy = (objects['ymax'] - objects['ymin']) / 2

        dxb = (objectsb['xmax'] - objectsb['xmin']) / 2
        dyb = (objectsb['ymax'] - objectsb['ymin']) / 2


        rmax = np.sqrt(dx*dx + dy*dy)
        rmaxb= np.sqrt(dxb*dxb + dyb*dyb)
        '''Frac is the percentage of flux we want contained within the radius,
        since we want half flux radius, frac is .5 '''
        
        frac=0.5
        rh, rh_flag = sep.flux_radius(image_sub, objects['x'], objects['y'], rmax, frac)
        rhb, rhb_flag = sep.flux_radius(image_sub, objectsb['x'], objectsb['y'], rmaxb, frac)

   
        #Sort the individual arrays so that the final table is sorted by flux
        #create sorting index by using flux. This is for the boosted threshold
        indb = np.argsort(flux_elipb)
        reverserb = np.arange(len(indb) - 1,-1,-1)
        rev_indb = np.take_along_axis(indb, reverserb, axis = 0)
        flux_elipb = np.take_along_axis(flux_elipb, rev_indb, axis = 0)
        #now apply it to all the axis
        fluxerr_elipb = np.take_along_axis(fluxerr_elipb, rev_indb, axis = 0)
        objectsb = np.take_along_axis(objectsb, rev_indb, axis = 0)
        rhb = np.take_along_axis(rhb, rev_indb, axis = 0)

        #now for normal threshold

        ind = np.argsort(flux_elip)
        reverser = np.arange(len(ind) - 1,-1,-1)
        rev_ind = np.take_along_axis(ind, reverser, axis = 0)
        flux_elip = np.take_along_axis(flux_elip, rev_ind, axis = 0)
        #now apply it to all the axis
        fluxerr_elip = np.take_along_axis(fluxerr_elip, rev_ind, axis = 0)
        objects = np.take_along_axis(objects, rev_ind, axis = 0)
        rh = np.take_along_axis(rh, rev_ind, axis = 0)

        
        # Select only the stars in the image: circular image and S/N > 10
        #Establish an elongation limit
        elim=1.5
        #Create cuts
        elong = (objects['a']/objects['b'])<elim
        seo_SN = (elong) & ((flux_elip/fluxerr_elip)<1000) & (fluxerr_elip != 0) & (flux_elip != 0)

        #Now do this for the low threshold sources
        elongb = (objectsb['a']/objectsb['b'])<elim
        seo_SNB = (elongb) & ((flux_elipb/fluxerr_elipb)<1000) & (fluxerr_elipb != 0) & (flux_elipb != 0)


        self.log.debug('Selected %d high thershold stars from Source Extrator catalog' % np.count_nonzero(seo_SN))
        self.log.debug('Selected %d low thershold stars from Source Extrator catalog' % np.count_nonzero(seo_SNB))

        #Calculate mean RH, its STD, and mean Elongation to report in header
        rhmean, rhstd = np.nanmean(rh[seo_SN]), mad_std(rh[seo_SN], ignore_nan = True)
        elmean= np.nanmean(objects['a'][seo_SN]/objects['b'][seo_SN])

        
        ### Make table with the restricted data from SEP
        # Collect data columns
        cols = []
        num = np.arange(1, len(objects['x'][seo_SN]) + 1 )
        cols.append(fits.Column(name='ID', format='D',
                                array=num))
        cols.append(fits.Column(name='X', format='D',
                                array=objects['x'][seo_SN],
                                unit='pixel'))
        cols.append(fits.Column(name='Y', format='D',
                                array=objects['y'][seo_SN],
                                unit='pixel'))
        cols.append(fits.Column(name='Uncalibrated Flux', format='D',
                                array=flux_elip[seo_SN],
                                unit='flux'))
        cols.append(fits.Column(name='Uncalibrated Fluxerr', format='D',
                                array=fluxerr_elip[seo_SN], unit='flux'))
        cols.append(fits.Column(name='Half-light Radius', format='D',
                                array=rh[seo_SN], unit='pixel'))



        # Now lets make a table using the Brighter threshold
        grid = []
        numb = np.arange(1, len(objectsb['x'][seo_SNB]) + 1 )
        grid.append(fits.Column(name='ID', format='D',
                                array=numb))
        grid.append(fits.Column(name='X', format='D',
                                array=objectsb['x'][seo_SNB],
                                unit='pixel'))
        grid.append(fits.Column(name='Y', format='D',
                                array=objectsb['y'][seo_SNB],
                                unit='pixel'))
        grid.append(fits.Column(name='Uncalibrated Flux', format='D',
                                array=flux_elipb[seo_SNB],
                                unit='flux'))
        grid.append(fits.Column(name='Uncalibrated Fluxerr', format='D',
                                array=fluxerr_elipb[seo_SNB], unit='flux'))
        grid.append(fits.Column(name='Half-light Radius', format='D',
                                array=rhb[seo_SNB], unit='pixel'))


        # Make table
        c = fits.ColDefs(cols)

        cbri=fits.ColDefs(grid)

        sources_table = fits.BinTableHDU.from_columns(c)

        sourceb_table= fits.BinTableHDU.from_columns(cbri)

        
        ### Make output data
        # Copy data from datain
        self.dataout = self.datain
        self.dataout.setheadval ('RHALF',rhmean, 'Mean half-power radius of stars (in pixels)') 
        self.dataout.setheadval ('RHALFSTD', rhstd, 'STD of masked mean of half-power radius')
        self.dataout.setheadval ('ELONG',elmean, 'Mean elong of accepted sources')
        self.dataout.tableset(sources_table.data,'Low Threshold Sources',sources_table.header)
        self.dataout.tableset(sourceb_table.data, 'High Threshold Sources', sourceb_table.header)
        self.dataout.setheadval ('EXTRACT_THRESH', extract_thresh, 'Extraction Thershold for Low Thershold Table')
        self.dataout.setheadval ('BRIGHT_FACTOR', bright_factor, 'Multiplier to create High Threshold Table')
       
        ### If requested make a text file with the sources list
        if self.getarg('sourcetable'):

            # Save region file

            filename = self.dataout.filenamebegin + 'FCALsources.reg'
            with open(filename, 'w+') as f:
                f.write("# Region file format: DS9 version 4.1\n")
                f.write("""global color=green dashlist=8 3 width=1 font="helvetica
                 10 normal roman" select=1 highlite=1 dash=0 fixed=0 edit=1 move=1
                  delete=1 include=1 source=1 image\n""")
                for i in range(len(objects['x'][seo_SN])):
                    f.write("circle(%.7f,%.7f,0.005) # text={%i}\n"%(objects['x']
                    [seo_SN][i],objects['y'][seo_SN][i],num[i]))

            # Save the table
            txtname = self.dataout.filenamebegin + 'FALsources.txt'
            ascii.write(self.dataout.tableget('Low Threshold Sources'),txtname,
                        format = self.getarg('sourcetableformat'))
            self.log.debug('Saved sources table under %s' % txtname)


if __name__ == '__main__':
    """ Main function to run the pipe step from command line on a file.
        Command:
        python stepparent.py input.fits -arg1 -arg2 . . .
        Standard arguments:
        --config=ConfigFilePathName.txt : name of the configuration file
        --test : runs the functionality test i.e. pipestep.test()
        --loglevel=LEVEL : configures the logging output for a particular level
    """
    StepSrcExtPy().execute()

'''HISTORY:
2018-09-019 - Started based on Amanda's code. - Marc Berthoud
'''
