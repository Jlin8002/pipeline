#!/usr/bin/env python
""" PIPE STEP ASTROMETRY- Version 1.0.0

    This pipe step calls the external program astrometry.net to add
    WCS information to the data.
    
    @author: Prechelt / Berthoud
"""

import logging # logging object library
import tempfile # temporary file library
import os # library for operating system calls
import time # library to manage delay and timeout
import string # library to join text
import subprocess # library to run subprocesses
from astropy import wcs # to get WCS coordinates
from astropy.coordinates import Angle
import astropy.units as u
from darepype.drp import DataFits
from darepype.drp import StepParent

class StepAstrometry(StepParent):
    """ HAWC Pipeline Step Parent Object
        The object is callable. It requires a valid configuration input
        (file or object) when it runs.
    """
    stepver = '0.2' # pipe step version
    
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
        self.name='astrometry'
        # Shortcut for pipeline reduction step and identifier for
        # saved file names.
        self.procname = 'WCS'
        # Set Logger for this pipe step
        self.log = logging.getLogger('pipe.step.%s' % self.name)
        ### Set Parameter list
        # Clear Parameter list
        self.paramlist = []
        # Append parameters
        self.paramlist.append(['astrocmd', 'cp %s %s',
                               'Command to call astrometry, should contain 2' +
                               'string placeholders for intput and output ' +
                               'filepathname'])
        self.paramlist.append(['verbose',False,
                               'log full astrometry output at DEBUG level'])
        self.paramlist.append(['delete_temp',False,
                               'Flag to delete temporary files generated by astrometry'])
        self.paramlist.append(['downsample', [2],
                               'List of downsample factors to try'])
        self.paramlist.append(['paramoptions', ['--guess-scale'],
                               'Parameter groups to run if the command fails'])
        self.paramlist.append(['timeout', 300,
                               'Timeout for running astrometry (seconds)'])
        self.paramlist.append(['searchradius', 5,
                               'Only search in indexes within "searchradius" (degrees) of the field center given by --ra and --dec (degrees)'])
        # confirm end of setup
        self.log.debug('Setup: done')

    def run(self):
        """ Runs the data reduction algorithm. The self.datain is run
            through the code, the result is in self.dataout.
        """
        ### Preparation
        # construct a temp file name that astrometry will output
        fp = tempfile.NamedTemporaryFile(suffix=".fits",dir=os.getcwd())
        # split off path name, because a path that is too long causes remap to
        # crash sometimes
        outname = os.path.split(fp.name)[1]
        fp.close()
        # Add input file path to ouput file and make new name
        outpath = os.path.split(self.datain.filename)[0]
        outnewname = os.path.join(outpath, outname.replace('.fits','.new') )
        outwcsname = os.path.join(outpath, outname.replace('.fits','.wcs') )
        # Make sure input data exists as file
        if not os.path.exists(self.datain.filename) :
            self.datain.save()
        # Make command string
        rawcommand = self.getarg('astrocmd') % (self.datain.filename, outname)

        # get estimated RA and DEC center values from the input FITS header
        try:
            ra = Angle(self.datain.getheadval('RA'), unit=u.hour).degree
            dec = Angle(self.datain.getheadval('DEC'), unit=u.deg).degree
        except:
            self.log.debug('FITS header missing RA/DEC -> searching entire sky')
        else:
        # update command parameters to use these values
            rawcommand = rawcommand + ' --ra %f --dec %f --radius %f' % (ra, dec, self.getarg('searchradius'))         

        ### Run Astrometry:
        #   This loop tries the downsample and param options until the fit is successful
        #    need either --scale-low 0.5 --scale-high 2.0 --sort-column FLUX
        #             or --guess-scale
        downsamples = self.getarg('downsample')
        paramoptions = self.getarg('paramoptions')
        for option in range(len(downsamples)*len(paramoptions)):
        #for downsample in self.getarg('downsample'):
            downsample = downsamples[option%len(downsamples)]
            paramoption = paramoptions[option//len(downsamples)]
            # Add options to command
            command = rawcommand + ' --downsample %d' % downsample + ' ' + paramoption
            optionstring = "Downsample=%s Paramopts=%s" % (downsample, paramoption[:10])
            # Run the process
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            self.log.debug('running command = %s' % command)
            # Wait for the process to be finished or timeout to be reached
            timeout = time.time() + self.getarg('timeout')
            while time.time() < timeout and process.poll() == None:
                time.sleep(1)
            poll = process.poll()
            if poll == None:
                process.kill()
                time.sleep(1)
            poll = process.poll()
            self.log.debug('command returns %d' % poll)
            if poll == 0 and os.path.exists(outnewname):
                self.log.debug('output file valid -> astrometry successful')
                break
            else:             
                self.log.debug('output file missing -> astrometry failed')
        # Print the output from astrometry (cut if necessary)
        if self.getarg('verbose') and poll == 0:
            output = process.stdout.read().decode()
            if len(output) > 1000:
                outlines = output.split('\n')
                output = outlines[:10]+['...','...']+outlines[-7:]
                output = '\n'.join(output)
            self.log.debug(output)

        ### Post processing
        # Read output file
        self.dataout = DataFits(config=self.config)
        self.log.debug('Opening astrometry.net output file %s' % outnewname)
        try:
            self.dataout.load(outnewname)
            self.dataout.filename = self.datain.filename
        except Exception as error:
            self.log.error("Unable to open astrometry. output file = %s"
                           % outname)
            raise error
        self.log.debug('Successful parameter options = %s' % optionstring)
        # Add history message
        histmsg = 'Astrometry.Net: At downsample = %d, search took %d seconds' % (downsample, time.time() - timeout + 300)
        self.dataout.setheadval('HISTORY', histmsg)
        # Add RA from astrometry
        w = wcs.WCS(self.dataout.header)
        n1 = float( self.dataout.header['NAXIS1']/2 )
        n2 = float( self.dataout.header['NAXIS2']/2 )
        ra, dec = w.all_pix2world(n1, n2, 1)
        self.dataout.header['CRPIX1']=n1
        self.dataout.header['CRPIX2']=n2
        self.dataout.header['CRVAL1']=float(ra)
        self.dataout.header['CRVAL2']=float(dec)
        self.dataout.header['RA'] = Angle(ra,  u.deg).to_string(unit=u.hour, sep=':')
        self.dataout.header['Dec']= Angle(dec, u.deg).to_string(sep=':')
        self.dataout.setheadval('HISTORY', 'Astrometry: Paramopts = ' + optionstring)
        # Delete temporary files
        if self.getarg('delete_temp'):
            os.remove(outnewname)
            os.remove(outwcsname)
        self.log.debug('Run: Done')
    
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
    StepAstrometry().execute()

""" === History ===
2018-10-12 MGB: - Add code to try different --downsample factors
                - Add timeout for running astrometry.net
                - Renamed StepAstrometry from StepAstrometrica
2016-10-15 First version
"""
