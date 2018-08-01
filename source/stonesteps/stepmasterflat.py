#!/usr/bin/env python
""" PIPE STEP MASTER BIAS - Version 1.0.0

    Code for StepMasterBias in pipeline: does the following
    
    !!!!!!!1 Add what the step needs as inputs, what it does and how, what the outputs are !!!!!!!!

    @author: Matt Merz
"""

import os # os library
import sys # sys library
import numpy # numpy library
import logging # logging object library
import astropy
import ccdproc # package for reducing optical CCD telescope data 
import matplotlib.pyplot as plt
from astropy import units as u
from astropy.io import fits #package to recognize FITS files
from drp.stepmiparent import StepMIParent
from drp.datafits import DataFits
from drp.steploadaux import StepLoadAux

class StepMasterFlat(StepLoadAux, StepMIParent):
    """ Stone Edge Pipeline Step Master Flat Object
        The object is callable. It requires a valid configuration input
        (file or object) when it runs.
    """
    stepver = '0.1' # pipe step version
    
    def setup(self):
        """ ### Names and Parameters need to be Set Here ###
            Sets the internal names for the function and for saved files.
            Defines the input parameters for the current pipe step.
            Setup() is called at the end of __init__
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
        self.name='masterflat'
        # Shortcut for pipeline reduction step and identifier for
        # saved file names.
        self.procname = 'mflat'
        # Set Logger for this pipe step
        self.log = logging.getLogger('stoneedge.pipe.step.%s' % self.name)
        ### Set Parameter list
        # Clear Parameter list
        self.paramlist = []
        # Append parameters !!!! WHAT PARAMETERS ARE NEEDED ????? !!!!!
        self.paramlist.append(['combinemethod','median',
                               'Specifies how the files should be combined - options are median, average, sum'])
        self.paramlist.append(['outputfolder','',
                               'Output directory location - default is the folder of the input files'])
        # Get parameters for StepLoadAux, replace auxfile with biasfile
        self.loadauxsetup('bias')
        # Get parameters for StepLoadAux, replace auxfile with darkfile
        self.loadauxsetup('dark')

    def run(self):
        """ Runs the combining algorithm. The self.datain is run
            through the code, the result is in self.dataout.
        """
        # Find master dark to subtract from master dark
        biaslist = self.loadauxname('bias', multi = False)
        darklist = self.loadauxname('dark', multi = False)
        if(len(biaslist) == 0):
            self.log.error('No bias calibration frames found.')
        if(len(darklist) == 0):
            self.log.error('No bias calibration frames found.')
        self.bias = ccdproc.CCDData.read(biaslist, unit='adu', relax=True)
        self.dark = ccdproc.CCDData.read(darklist, unit='adu', relax=True)
        # Create empy list for filenames of loaded frames
        filelist=[]
        for fin in self.datain:
            self.log.debug("Input filename = %s" % fin.filename)
            filelist.append(fin.filename)
        # Make a dummy dataout
        self.dataout = DataFits(config = self.config)
        if len(self.datain) == 0:
            self.log.error('Flat calibration frame not found.')
            raise RuntimeError('No flat file(s) loaded')
        self.log.debug('Creating master flat frame...')
        # Create master frame: if there is just one file, turn it into master bias or else combine all to make master bias
        if (len(filelist) == 1):
            self.flat = ccdproc.CCDData.read(filelist[0], unit='adu', relax=True)
            self.flat = ccdproc.subtract_bias(self.flat, self.bias, add_keyword=False)
            self.flat = ccdproc.subtract_dark(self.flat, self.dark, scale=True, exposure_time='EXPTIME', exposure_unit=u.second, add_keyword=False)
        else:
            #bias and dark correct frames
            flatlist=[]
            for i in filelist:
                flat =ccdproc.CCDData.read(i, unit='adu', relax=True)
                flatsubbias = ccdproc.subtract_bias(flat, self.bias, add_keyword=False)
                flatsubbiasdark = ccdproc.subtract_dark(flatsubbias, self.dark, scale=True, exposure_time='EXPTIME', exposure_unit=u.second, add_keyword=False)
                flatlist.append(flatsubbiasdark)
            #scale the flat component frames to have the same mean value, 10000.0
            scaling_func = lambda arr: 10000.0/numpy.ma.median(arr)
            #combine them
            self.flat = ccdproc.combine(flatlist, method=self.getarg('combinemethod'), scale=scaling_func, unit='adu', add_keyword=False)
#             self.flat = ccdproc.combine(filelist, method=self.getarg('combinemethod'), unit='adu', add_keyword=False)
        self.dataout.header=self.datain[0].header
        self.dataout.imageset(self.flat)
        # rename output filename
        if self.getarg('outputfolder')!='':
            self.dataout.filename = os.path.join(self.getarg('outputfolder'), os.path.split(filelist[0])[1])
        else:
            self.dataout.filename = filelist[0]
        
        
if __name__ == '__main__':
    """ Main function to run the pipe step from command line on a file.
        Command:
          python stepparent.py input.fits -arg1 -arg2 . . .
        Standard arguments:
          --config=ConfigFilePathName.txt : name of the configuration file
          -t, --test : runs the functionality test i.e. pipestep.test()
          --loglevel=LEVEL : configures the logging output for a particular level
          -h, --help : Returns a list of 
    """
    StepMasterBias().execute()
        
        
""" === History ===
    2018-07-?23 New step created based on StepRGB - Matt Merz
"""