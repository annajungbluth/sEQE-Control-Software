#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Sep 28 11:59:40 2018

@author: jungbluth
"""

import io
import itertools
import math
import os
import re
import sys
import time
import logging
import warnings

import GUI_template
import matplotlib
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import pandas as pd
import serial
import zhinst.utils
import zhinst.ziPython
# for the gui
from PyQt5 import QtCore, QtGui, QtWidgets
from matplotlib import style
from numpy import *
from scipy.interpolate import interp1d


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        
        QtWidgets.QMainWindow.__init__(self)
        
        warnings.filterwarnings("ignore")
        
        self.logger = self.get_logger()
        
        # Set up the user interface from Designer
        
        self.ui = GUI_template.Ui_MainWindow()
        self.ui.setupUi(self)         
        
        # Connections
        
        self.mono_connected = False   # Set the monochromator connection to False
        self.lockin_connected = False   # Set the Lock-in connection to False
        self.filter_connected = False  # Set the filterwheel connection to False
        
        # General Setup
         
        self.channel = 1
        self.c = str(self.channel-1) 
        self.c6 = str(6)

        self.do_plot = True

        self.complete_scan = False

        self.filter_addition = 'None' ####################################################################################
        
        # Handle Monochromator Buttons
        
        self.ui.connectButton_Mono.clicked.connect(self.connectToMono)  # Connect only to Monochromator        
        self.ui.monoGotoButton.clicked.connect(self.MonoHandleWavelengthButton)   # Go to specific wavelength
        self.ui.monoSpeedButton.clicked.connect(self.MonoHandleSpeedButton)   # Set scan speed
        self.ui.monoGratingButton.clicked.connect(self.MonoHandleGratingButtons)   # Change grating    
        self.ui.monoFilterButton.clicked.connect(self.MonoHandleFilterButton)   # Change filter
        
        self.ui.monoFilterInitButton.clicked.connect(self.MonoHandleFilterInitButton)   # Initialize filter
            
        # Handle Lock-in Buttons
        
        self.ui.connectButton_Lockin.clicked.connect(self.connectToLockin)   # Connect only to Lock-in         
        self.ui.lockinParameterButton.clicked.connect(self.LockinHandleParameterButton)   # Set Lock-in parameters

        # Handle Filterwheel Buttons

        self.ui.connectButton_Filter.clicked.connect(self.connectToFilter) # Connect only to Filterwheel
         
        # Handle Combined Buttons

        self.ui.connectButton.clicked.connect(self.connectToEquipment)

        self.ui.measureButtonRef_Si.clicked.connect(self.MonoHandleSiRefButton)
        self.ui.measureButtonRef_GA.clicked.connect(self.MonoHandleGARefButton)        
        self.ui.measureButtonDev.clicked.connect(self.MonoHandleMeasureButton)        
        self.ui.stopButton.clicked.connect(self.HandleStopButton)

        self.ui.completeScanButton_start.clicked.connect(self.MonoHandleCompleteScanButton)  #########################################################################################
        self.ui.completeScanButton_stop.clicked.connect(self.HandleStopCompleteScanButton)   #########################################################################################
        
        # Import photodiode calibration files

        Si_file = pd.ExcelFile("FDS100-CAL.xlsx") # The files are in the sEQE Analysis folder
#        print(Si_file.sheet_names)
        self.Si_cal = Si_file.parse('Sheet1')
#        print(self.Si_cal)
        
        InGaAs_file = pd.ExcelFile("FGA21-CAL.xlsx")
        self.InGaAs_cal = InGaAs_file.parse('Sheet1')     

        # Path to USB connections 
        self.filter_usb = '/dev/ttyUSB0' # NOTE: Change this if necessary
        self.mono_usb = '/dev/ttyUSB1' # NOTE: Change this if necessary

        # Path to save data
        self.save_path = '/home/jungbluthl/Desktop/sEQE Data' # NOTE: Change this if necessary
        
    # Close connection to Monochromator when window is closed
    
    def __del__(self):
        try:
            self.p.close()
        except:
            pass 

# -----------------------------------------------------------------------------------------------------------        

    #### Functions to connect to Monochromator and Lock-in

# -----------------------------------------------------------------------------------------------------------
        
    # Establish serial connection to Monochromator
    
    def connectToMono(self):
        """Function to establish connection to monochromator
        :return: None
        """
        self.p = serial.Serial(self.mono_usb, 9600, timeout=0)    
        
        self.p.write('HELLO\r'.encode())   # "Hello" initializes the Monochromator
        time.sleep(25)   # Sleep function makes window time out. This is to avoid that the user sends signals while the Monochromator is still initializing
        self.mono_connected = self.waitForOK()   # Checks for OK response of Monochromator

        if self.mono_connected:
            self.logger.info('Connection to Monochromator Established')
            self.ui.imageConnect_mono.setPixmap(QtGui.QPixmap("Button_on.png"))           
    
    # Check Monochromator response
    
    def waitForOK(self):
        """Function to wait for acceptance signal from monochromator
        :raises LoggerError: Raises error if monochromator connection failed
        ...
        :return: Returns True of connection successful, and False otherwise
        :rtype: bool
        """
        ret = False
        self.p.timeout = 40000
        shouldbEOk = self.p.readline() 
        
        if (shouldbEOk == ' ok\r\n'.encode()) or (shouldbEOk == '  ok\r\n'.encode()):
            ret = True
        else:
            self.logger.error('Connection to Monochromator Could Not Be Established')   
            
        self.p.timeout = 0
        return ret        
        
    # Establish connection to LOCKIN
    
    def connectToLockin(self):    
        """Function to establish connection to Lockin
        :return: Returns Zurich Instruments localhost name and device details
        """    
        self.lockin_connected = False
        
        # Open connection to ziServer
        daq = zhinst.ziPython.ziDAQServer('localhost', 8005) # NOTE: Modify address if necessary
        self.daq = daq
        
        # Detect device
        self.device = zhinst.utils.autoDetect(daq)

        self.logger.info('Connection to Lock-In Established')
        
        self.lockin_connected = True       
        self.ui.imageConnect_lockin.setPixmap(QtGui.QPixmap("Button_on.png"))
        
        return self.daq, self.device

    # Establish connection to Filterwheel

    def connectToFilter(self):
        """Function to establish connection to filter wheel
        :raises SerialException: Raises exception if filter wheel USB port is inaccessible
        :raises OSError: Raises exception if filter wheel USB port is inaccessible
        ...
        :return: None
        """ 
        try:
            self._fw = serial.Serial(port=self.filter_usb, baudrate=115200,
                                     bytesize=8, parity='N', stopbits=1,
                                     timeout=1, xonxoff=0, rtscts=0)
        except  serial.SerialException as ex:
            self.logger.error('Port {0} is unavailable: {1}'.format(self.filter_usb, ex))
            self.filter_connected = False
            return
        except  OSError as ex:
            self.logger.error('Port {0} is unavailable: {1}'.format(self.filter_usb, ex))
            self.filter_connected = False
            return

        self._sio = io.TextIOWrapper(io.BufferedRWPair(self._fw, self._fw, 1),
                                     newline=None, encoding='ascii')

        self.logger.info("Connection to External Filter Wheel Established")

#        self._sio.write('*idn?\r')
#        devInfo = self._sio.readlines(2048)[1][:-1]
#        print(devInfo)

        self._sio.flush()
        self.filter_connected = True
        self.ui.imageConnect_filter.setPixmap(QtGui.QPixmap("Button_on.png"))

# -----------------------------------------------------------------------------------------------------------        
        
    # Establish connection to both
        
    def connectToEquipment(self):
        """Function to establish connection to monochromator, Lockin & filter wheel
        :return: None
        """
        self.connectToLockin()
        self.connectToMono()
        self.connectToFilter()
        
        self.ui.imageConnect.setPixmap(QtGui.QPixmap("Button_on.png"))        
    
# -----------------------------------------------------------------------------------------------------------        
    
    #### Functions to handle parameter buttons for Monochromator and Lock-in
    
# -----------------------------------------------------------------------------------------------------------            
       
    ## Monochromator Functions
    
    # Set and GOTO wavelength
    
    def MonoHandleWavelengthButton(self):   # Function sets desired wavelength and calls chooseWavelength function
        """Function to read wavelength value from GUI
        :return: None
        """
        wavelength = self.ui.pickNM.value()
        self.chooseWavelength(wavelength)
      
    def chooseWavelength(self, wavelength):   # Function to send GOTO command to monochromator
        """Function to send wavelength command to monochromator
        :param wavelength: target wavelength
        :type wavelength: float, required
        ...
        :raises LoggerError: Raises error if monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:
            print('%d nm' % wavelength)
            self.p.write('{:.2f} GOTO\r'.format(wavelength).encode())
            self.waitForOK()
                
        else:
            self.logger.error('Monochromator Not Connected')
            
    # Update the scan speed
            
    def MonoHandleSpeedButton(self):   # Function sets desired scan speed and calls chooseScanSpeed function
        """Function to read monochromator speed from GUI
        :return: None
        """
        speed = self.ui.pickScanSpeed.value()
        self.chooseScanSpeed(speed)
        
    def chooseScanSpeed(self, speed):   # Function to send scan speed command to monochromator
        """Function to send scan speed command to monochromator
        :param speed: monochromator grating scan speed
        :type speed: float, required
        ...
        :raises LoggerError: Raises error if monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:
#            self.logger.info('Updating Scan Speed to %d nm/min.' % speed)
            self.p.write('{:.2f} NM/MIN\r'.format(speed).encode())
            self.waitForOK()
        else:
            self.logger.error('Monochromator Not Connected')   

    # Set and move to grating 
    
    def MonoHandleGratingButtons(self):   # Function sets desired grating number and calls chooseGrating function
        """Function to read grating number from monochromator
        :return: None
        """
        if self.ui.Blaze_300.isChecked():
            gratingNo = 1
        elif self.ui.Blaze_750.isChecked():
            gratingNo = 2
        elif self.ui.Blaze_1600.isChecked():
            gratingNo = 3
        self.chooseGrating(gratingNo)
      
    def chooseGrating(self, gratingNo):   # Function to send grating command to monochromator
        """Function to send grating command to monochromator
        :param gratingNo: Monochromator grating number
        :type gratingNo: float, required
        ...
        :raises LoggerError: Raises error if monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:
            self.logger.info('Moving to Grating %d' % gratingNo)
            self.p.write('{:d} grating\r'.format(gratingNo).encode())
            self.waitForOK()
        else:
            self.logger.error('Monochromator Not Connected')
            
    # Update filter number
            
    def MonoHandleFilterButton(self):
        """Function to read filter position from GUI
        :return: None
        """
        filterNo = int(self.ui.pickFilter.value())
        self.chooseFilter(filterNo)

    def chooseFilter(self, filterNo):
        """Function to send filter selection command to filter wheel
        :param filterNo: Filter position
        :type filterNo: float, required
        ...
        :raises LoggerError: Raises error if monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:
#            self.logger.info('Moving to Monochromator Filter %d' % filterNo)
            self.p.write('{:d} FILTER\r'.format(filterNo).encode())
            self.waitForOK()
        else:
            self.logger.error('Monochromator Not Connected')  

    # Initialize filter 

    def MonoHandleFilterInitButton(self):
        """Function to read filter initialization position from GUI
        :return: None
        """
        filterStart = self.ui.pickFilterInitStart.value()
        filterDiff = int(8-filterStart)
        self.initializeFilter(filterDiff)                

    def initializeFilter(self, filterDiff):
        """Function to initialize filter wheel
        :param filterDiff: Difference between filter position and initialization position
        :type filterDiff: int, required
        ...
        :raises LoggerError: Raises error if monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:
            self.logger.info('Initializing Monochromator Filter Wheel')
            self.p.write('{:d} FILTER\r'.format(filterDiff).encode())
            self.p.write('FHOME\r'.encode())
            self.waitForOK()
            self.ui.imageInit_filterwheel.setPixmap(QtGui.QPixmap("Button_on.png"))
        else:
            self.logger.error('Monochromator Not Connected') 
    
# -----------------------------------------------------------------------------------------------------------        
    
    ## Lock-in Functions
    
    # Define and set Lock-in parameters
    
    def LockinHandleParameterButton(self):
        """Function to read Lockin amplification value from GUI
        :return: None
        """
        if self.lockin_connected:
            self.amplification = self.ui.pickAmp.value()
            self.LockinUpdateParameters()
        
    def LockinUpdateParameters(self):   # Function sets desired Lock-in parameters and calls setParameter function 
        """Function to update Lockin parameters
        :raises LoggerError: Raises error if Lockin not connected
        ...
        :return: None
        """        
        if self.lockin_connected:  
            self.c_2 = str(self.channel) # Channel 2, with value 1, for the reference input
            self.tc = self.ui.pickTC.value() # Import value for time constant
            self.rate = self.ui.pickDTR.value() # Import value for data transfer rate
            self.lowpass = self.ui.pickLPFO.value() # Import value for low pass filter order
            self.range = 2 # This sets the default voltage range to 2
            self.ac = 0 # AC off
            self.imp50 = 0 # 50 Ohm off
            self.imp50_2 = 1 # Turn on 50 Ohm on channel 2 to attenuate signal from chopper controller as reference signal
            self.diff = 1 # Diff off
#            if self.ui.acButton.isChecked(): # AC on if button is checked
#                self.ac = 1
#            if self.ui.imp50Button.isChecked(): # 50 Ohm on if button is checked
#                self.imp50 = 1
#            if self.ui.diffButton.isChecked(): # Diff on if button is checked
#                self.diff = 1                
#            self.frequency = self.ui.pickFreq.value() # For manual frequency control. The frequency tab is currently not implemented in the GUI
            
            self.setParameters()
            self.logger.info('Updating Lock-In Settings')
            
        else:
            self.logger.error("Lock-In Not Connected")
             
    def setParameters(self):       
        """Function to set default Lockin parameters
        :return: None
        """
 #       c = str(0)      
 #       print(self.amplification)
     
        # Disable all outputs and all demods
        general_setting = [
             [['/', self.device, '/demods/0/trigger'], 0],
             [['/', self.device, '/demods/1/trigger'], 0],
             [['/', self.device, '/demods/2/trigger'], 0],
             [['/', self.device, '/demods/3/trigger'], 0],
             [['/', self.device, '/demods/4/trigger'], 0],
             [['/', self.device, '/demods/5/trigger'], 0],
             [['/', self.device, '/sigouts/0/enables/*'], 0],
             [['/', self.device, '/sigouts/1/enables/*'], 0]
        ]
        self.daq.set(general_setting)
       
        # Set test settings
        t1_sigOutIn_setting = [
            [['/', self.device, '/sigins/',self.c,'/diff'], self.diff],  # Diff Button (Enable for differential mode to measure the difference between +In and -In.)
            [['/', self.device, '/sigins/',self.c,'/imp50'], self.imp50],  # 50 Ohm Button (Enable to switch input impedance between low (50 Ohm) and high (approx 1 MOhm). Select for signal frequencies of > 10 MHz.) 
            [['/', self.device, '/sigins/',self.c,'/ac'], self.ac],  # AC Button (Enable for AC coupling to remove DC signal. Cutoff frequency = 1kHz) 
            [['/', self.device, '/sigins/',self.c,'/range'], self.range],  # Input Range               
            [['/', self.device, '/demods/',self.c,'/order'], self.lowpass],  # Low-Pass Filter Order                        
            [['/', self.device, '/demods/',self.c,'/timeconstant'], self.tc],  # Time Constant
            [['/', self.device, '/demods/',self.c,'/rate'], self.rate],  # Data Transfer Rate 
            [['/', self.device, '/demods/',self.c,'/oscselect'], self.channel-1],  # Oscillators
            [['/', self.device, '/demods/',self.c,'/harmonic'], 1],  # Harmonicss
            [['/', self.device, '/demods/',self.c,'/phaseshift'], 0],  # Phase Shift       
            [['/', self.device, '/zctrls/',self.c,'/tamp/0/currentgain'], self.amplification],  #  Amplifier Setting
            [['/', self.device, '/demods/',self.c,'/adcselect'], self.channel-1], # ???
                        
        # For locked reference signal
            [['/', self.device, '/sigins/', self.c_2,'/imp50'], self.imp50_2],  # 50 Ohm Button (Enable to switch input impedance between low (50 Ohm) and high (approx 1 MOhm). Select for signal frequencies of > 10 MHz.)
            [['/', self.device, '/plls/',self.c,'/enable'], 1],  # Manual [0], External Reference [1]
            [['/', self.device, '/plls/',self.c,'/adcselect'], 1], # ???

        # For manual reference signal - The frequency tab is currently not implemented in the GUI
#            [['/', self.device, '/plls/',self.c,'/enable'], 0],  # Manual [0], External Reference [1]
#            [['/', self.device, '/oscs/',self.c,'/freq'], self.frequency],  # Demodulation Frequency
            
        # Additional settings ?                        
    #        [['/', self.device, '/sigouts/',self.c,'/add'], -179.8390],  # Output Add Button (Adds signal from "Add" connection)
    #        [['/', self.device, '/sigouts/',self.c,'/on'], 1],  # Turn on Output Channel
    #        [['/', self.device, '/sigouts/',self.c,'/enables/',c6], 1],  # Enable Output Channel
    #        [['/', self.device, '/sigouts/',self.c,'/range'], 1],  # Output Range
    #        [['/', self.device, '/sigouts/',self.c,'/amplitudes/',c6], amplitude],  # Output Amplitude
    #        [['/', self.device, '/sigouts/',self.c,'/offset'], 0],  # Output Offset
            
        ]
        self.daq.set(t1_sigOutIn_setting);       
        time.sleep(1)  # wait 1s to get a settled lowpass filter
        self.daq.flush()   # clean queue
        
#        self.logger.info("Lock-in settings have been updated")
        
# -----------------------------------------------------------------------------------------------------------        
    
    #### Functions to handle filter and grating changes

# -----------------------------------------------------------------------------------------------------------  
  
        
    def monoCheckFilter(self, wavelength):   # Filter switching points from GUI
        """Function to update position of first filter wheel from GUI defaults 
        :param wavelength: Current wavelength position of monochromator
        :type wavelength: float, required
        ...
        :raises LoggerError: Raises error if filter wheel commands are invalid or monochromator not connected
        ...
        :return: None
        """
        if self.mono_connected:                       
            self.p.write('?filter\r'.encode())
            self.p.timeout = 30000
            response = self.p.readline() 
            
            if (response == '1  ok\r\n'.encode()) or (response == ' 1  ok\r\n'.encode()):
                filterNo = 1
            elif (response == '2  ok\r\n'.encode()) or (response == ' 2  ok\r\n'.encode()):
                filterNo = 2 
            elif (response == '3  ok\r\n'.encode()) or (response == ' 3  ok\r\n'.encode()):
                filterNo = 3
            elif (response == '4  ok\r\n'.encode()) or (response == ' 4  ok\r\n'.encode()):
                filterNo = 4 
            elif (response == '5  ok\r\n'.encode()) or (response == ' 5  ok\r\n'.encode()):
                filterNo = 5
            elif (response == '6  ok\r\n'.encode()) or (response == ' 6  ok\r\n'.encode()):
                filterNo = 6
            else:   # Do I need this?
                self.logger.error('Error: Filter Response')

            startNM_F2 = int(self.ui.startNM_F2.value())
            stopNM_F2 = int(self.ui.stopNM_F2.value())                
            startNM_F3 = int(self.ui.startNM_F3.value())
            stopNM_F3 = int(self.ui.stopNM_F3.value())
            startNM_F4 = int(self.ui.startNM_F4.value())
            stopNM_F4 = int(self.ui.stopNM_F4.value())
            startNM_F5 = int(self.ui.startNM_F5.value())
            stopNM_F5 = int(self.ui.stopNM_F5.value())            

            if startNM_F2 <= wavelength < stopNM_F2: # Filter 3 [FESH0700]: from 350 - 649  -- including start, excluing end
                shouldbeFilterNo = 2                  
            elif startNM_F3 <= wavelength < stopNM_F3: # Filter 3 [FESH0700]: from 350 - 649  -- including start, excluing end
                shouldbeFilterNo = 3  
            elif startNM_F4 <= wavelength < stopNM_F4: # Filter 4 [FESH1000]: from 650 - 984  -- including start, excluding end
                shouldbeFilterNo = 4 
            elif startNM_F5 <= wavelength <= stopNM_F5: # Filter 5 [FELH0950]: from 985 - 1800  -- including start, including end
                shouldbeFilterNo = 5
            else:   
#                shouldbeFilterNo = 2
                self.logger.error('Error: Filter Out Of Range')
                
            if shouldbeFilterNo != filterNo:
                self.chooseFilter(shouldbeFilterNo)    
                
                
                # Take data and discard it, this is required to avoid kinks
                # Poll data for 5 time constants, second parameter is poll timeout in [ms] (recomended value is 500ms) 
                dataDict = self.daq.poll(5*self.tc,500)  # Dictionary with ['timestamp']['x']['y']['frequency']['phase']['dio']['trigger']['auxin0']['auxin1']['time']
                                   
            else:
                pass
                
        else:
            self.logger.error('Monochromator Not Connected') 
    
    
    def monoCheckGrating(self, wavelength):   # Grating switching points from GUI
        """Function to update monochromator grating position from GUI defaults 
        :param wavelength: Current wavelength position of monochromator
        :type wavelength: float, required
        ...
        :raises LoggerError: Raises error if grating commands are invalid or monochromator not connected
        ...
        :return: None
        """   
        if self.mono_connected:
            self.p.write('?grating\r'.encode())
            self.p.timeout = 30000
            response = self.p.readline() 
            
            if (response == '1  ok\r\n'.encode()) or (response == ' 1  ok\r\n'.encode()):
                gratingNo = 1
            elif (response == '2  ok\r\n'.encode()) or (response == ' 2  ok\r\n'.encode()):
                gratingNo = 2 
            elif (response == '3  ok\r\n'.encode()) or (response == ' 3  ok\r\n'.encode()):
                gratingNo = 3
            else:   # Do I need this?
                self.logger.error('Error: Grating Response')
                
            startNM_G1 = int(self.ui.startNM_G1.value())
            stopNM_G1 = int(self.ui.stopNM_G1.value())
            startNM_G2 = int(self.ui.startNM_G2.value())
            stopNM_G2 = int(self.ui.stopNM_G2.value())
            startNM_G3 = int(self.ui.startNM_G3.value())
            stopNM_G3 = int(self.ui.stopNM_G3.value()) 
                
            if startNM_G1 <= wavelength < stopNM_G1: # Grating 1: from 350 - 549  -- including start, excluding end
                shouldbeGratingNo = 1  
            elif startNM_G2 <= wavelength < stopNM_G2: # Grating 2: from 550 - 1299  -- including start, excluding end
                shouldbeGratingNo = 2  
            elif startNM_G3 <= wavelength <= stopNM_G3: # Grating 3: from 1300 - 1800  -- including start, including end
                shouldbeGratingNo = 3
            else:   # Do I need this?
                self.logger.error('Error: Grating Out Of Range')
                
            if shouldbeGratingNo != gratingNo:
                self.chooseGrating(shouldbeGratingNo)
                
                # Take data and discard it, this is required to avoid kinks                
                # Poll data for 5 time constants, second parameter is poll timeout in [ms] (recomended value is 500ms) 
                dataDict = self.daq.poll(5*self.tc,500)  # Dictionary with ['timestamp']['x']['y']['frequency']['phase']['dio']['trigger']['auxin0']['auxin1']['time']
   
            else:
                pass
                
        else:
            self.logger.error('Monochromator Not Connected')

# -----------------------------------------------------------------------------------------------------------

    #### Function to handle filter changes of Thorlabs filterwheel

# -----------------------------------------------------------------------------------------------------------

    def changeFilter(self, pos):
        """Function to update position of second filter wheel 
        :param pos: Target filter position, between 1-6
        :type pos: int, required
        ...
        :raises LoggerError: Raises error if second filter wheel not connected
        ...
        :return: Returns True if connection to second filter wheel is successful, False otherwise
        """
        if not self.filter_connected:
            self.logger.error("External Filter Wheel Not Connected")
            return False

        #ans = 'ERROR'

        self._sio.flush()
        self._sio.write('pos=' + str(pos) + '\r')

        # ans = self._sio.readlines(2048)
        # regerr = re.compile("Command error.*")
        # errors = [m.group(0) for l in ans for m in [regerr.search(l)] if m]
        # # print 'res=',repr(res),'ans=',repr(ans),cmd
        # if len(errors) > 0:
        #     print(errors[0])
        #     return False
        # ans = self.query(cmd + '?')
        # print 'ans=',repr(ans),cmd+'?'
        # print(ans)

        return True
        
# -----------------------------------------------------------------------------------------------------------        
    
    #### Functions to handle measurement buttons
    
# -----------------------------------------------------------------------------------------------------------  

    # Set parameters and measure Silicon reference diode

    def MonoHandleSiRefButton(self):
        """Function to meausure silicon reference photodiode
        :return: None
        """
        start_si = self.ui.startNM_Si.value()
        stop_si = self.ui.stopNM_Si.value()
        step_si = self.ui.stepNM_Si.value()
        amp_si = self.ui.pickAmp_Si.value()
            
        self.amplification = amp_si
        self.LockinUpdateParameters()
        self.MonoHandleSpeedButton()
        
        scan_list = self.createScanJob(start_si, stop_si, step_si)
        self.HandleMeasurement(scan_list, start_si, stop_si, step_si, amp_si, 1)
        
        self.chooseFilter(1)        
        self.ui.imageRef_Si.setPixmap(QtGui.QPixmap("Button_on.png"))      
        self.logger.info('Finished Measurement')        
    
        
    # Set parameters and measure InGaAs reference diode
               
    def MonoHandleGARefButton(self):
        """Function to meausure silicon reference photodiode
        :return: None
        """
        start_ga = self.ui.startNM_GA.value()
        stop_ga = self.ui.stopNM_GA.value()
        step_ga = self.ui.stepNM_GA.value()
        amp_ga = self.ui.pickAmp_GA.value()

        self.amplification = amp_ga
        self.LockinUpdateParameters()
        self.MonoHandleSpeedButton()

        scan_list = self.createScanJob(start_ga, stop_ga, step_ga)
        self.HandleMeasurement(scan_list, start_ga, stop_ga, step_ga, amp_ga, 2)
        
        self.chooseFilter(1)              
        self.ui.imageRef_GA.setPixmap(QtGui.QPixmap("Button_on.png"))       
        self.logger.info('Finished Measurement')  
        
        
    # Set parameters and measure sample
        
    def MonoHandleMeasureButton(self):
        """Function to meausure samples with different wavelength ranges
        :return: None
        """
        if self.ui.Range1.isChecked():    
            start_r1 = self.ui.startNM_R1.value()
            stop_r1 = self.ui.stopNM_R1.value()
            step_r1 = self.ui.stepNM_R1.value()
            amp_r1 = self.ui.pickAmp_R1.value()

            self.amplification = amp_r1
            self.LockinUpdateParameters()
            self.MonoHandleSpeedButton()
                        
            scan_list = self.createScanJob(start_r1, stop_r1, step_r1)
            self.HandleMeasurement(scan_list, start_r1, stop_r1, step_r1, amp_r1, 3)
        
        if self.ui.Range2.isChecked():         
            start_r2 = self.ui.startNM_R2.value()
            stop_r2 = self.ui.stopNM_R2.value()
            step_r2 = self.ui.stepNM_R2.value()
            amp_r2 = self.ui.pickAmp_R2.value()

            self.amplification = amp_r2
            self.LockinUpdateParameters()
            self.MonoHandleSpeedButton()        
            
            scan_list = self.createScanJob(start_r2, stop_r2, step_r2)
            self.HandleMeasurement(scan_list, start_r2, stop_r2, step_r2, amp_r2, 3)
            
        if self.ui.Range3.isChecked():   
            start_r3 = self.ui.startNM_R3.value()
            stop_r3 = self.ui.stopNM_R3.value()
            step_r3 = self.ui.stepNM_R3.value()
            amp_r3 = self.ui.pickAmp_R3.value()

            self.amplification = amp_r3
            self.LockinUpdateParameters()
            self.MonoHandleSpeedButton()
            
            scan_list = self.createScanJob(start_r3, stop_r3, step_r3)
            self.HandleMeasurement(scan_list, start_r3, stop_r3, step_r3, amp_r3, 3)       
        
        if self.ui.Range4.isChecked():   
            start_r4 = self.ui.startNM_R4.value()
            stop_r4 = self.ui.stopNM_R4.value()
            step_r4 = self.ui.stepNM_R4.value()
            amp_r4 = self.ui.pickAmp_R4.value()

            self.amplification = amp_r4
            self.LockinUpdateParameters()
            self.MonoHandleSpeedButton()
            
            scan_list = self.createScanJob(start_r4, stop_r4, step_r4)
            self.HandleMeasurement(scan_list, start_r4, stop_r4, step_r4, amp_r4, 3)
            
        self.chooseFilter(1)
        self.ui.imageMeasure.setPixmap(QtGui.QPixmap("Button_on.png"))
        self.logger.info('Finished Measurement')


    # Set parameters for complete scan and measure sample

    def MonoHandleCompleteScanButton(self):
        """Function to meausure samples with different filters
        :return: None
        """
        self.complete_scan = True

        if self.ui.scan_noFilter.isChecked():

            self.changeFilter(1)

            if self.changeFilter(1):

                self.filter_addition = 'no'

                self.logger.info('Moving to Open Filter Position')

                start_f1 = self.ui.scan_startNM_1.value()
                stop_f1 = self.ui.scan_stopNM_1.value()
                step_f1 = self.ui.scan_stepNM_1.value()
                amp_f1 = self.ui.scan_pickAmp_1.value()

                self.amplification = amp_f1
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton() 
                
                scan_list = self.createScanJob(start_f1, stop_f1, step_f1)
                self.HandleMeasurement(scan_list, start_f1, stop_f1, step_f1, amp_f1, 3)
                
        if self.ui.scan_Filter2.isChecked():

            self.changeFilter(2)

            if self.changeFilter(2):
                
                self.filter_addition = str(int(self.ui.cuton_filter_2.value()))

                self.logger.info('Moving to %s nm Filter' % self.filter_addition)

                start_f2 = self.ui.scan_startNM_2.value()
                stop_f2 = self.ui.scan_stopNM_2.value()
                step_f2 = self.ui.scan_stepNM_2.value()
                amp_f2 = self.ui.scan_pickAmp_2.value()

                self.amplification = amp_f2
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton()

                scan_list = self.createScanJob(start_f2, stop_f2, step_f2)
                self.HandleMeasurement(scan_list, start_f2, stop_f2, step_f2, amp_f2, 3)

        if self.ui.scan_Filter3.isChecked():

            self.changeFilter(3)

            if self.changeFilter(3):
                
                self.filter_addition = str(int(self.ui.cuton_filter_3.value()))

                self.logger.info('Moving to %s nm Filter' % self.filter_addition)

                start_f3 = self.ui.scan_startNM_3.value()
                stop_f3 = self.ui.scan_stopNM_3.value()
                step_f3 = self.ui.scan_stepNM_3.value()
                amp_f3 = self.ui.scan_pickAmp_3.value()

                self.amplification = amp_f3
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton()

                scan_list = self.createScanJob(start_f3, stop_f3, step_f3)
                self.HandleMeasurement(scan_list, start_f3, stop_f3, step_f3, amp_f3, 3)

        if self.ui.scan_Filter4.isChecked():

            self.changeFilter(4)

            if self.changeFilter(4):
                
                self.filter_addition = str(int(self.ui.cuton_filter_4.value()))

                self.logger.info('Moving to %s nm Filter' % self.filter_addition)

                start_f4 = self.ui.scan_startNM_4.value()
                stop_f4 = self.ui.scan_stopNM_4.value()
                step_f4 = self.ui.scan_stepNM_4.value()
                amp_f4 = self.ui.scan_pickAmp_4.value()

                self.amplification = amp_f4
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton()

                scan_list = self.createScanJob(start_f4, stop_f4, step_f4)
                self.HandleMeasurement(scan_list, start_f4, stop_f4, step_f4, amp_f4, 3)

        if self.ui.scan_Filter5.isChecked():

            self.changeFilter(5)

            if self.changeFilter(5):

                self.filter_addition = str(int(self.ui.cuton_filter_5.value()))

                self.logger.info('Moving to %s nm Filter' % self.filter_addition)

                start_f5 = self.ui.scan_startNM_5.value()
                stop_f5 = self.ui.scan_stopNM_5.value()
                step_f5 = self.ui.scan_stepNM_5.value()
                amp_f5 = self.ui.scan_pickAmp_5.value()

                self.amplification = amp_f5
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton()

                scan_list = self.createScanJob(start_f5, stop_f5, step_f5)
                self.HandleMeasurement(scan_list, start_f5, stop_f5, step_f5, amp_f5, 3)

        if self.ui.scan_Filter6.isChecked():

            self.changeFilter(6)

            if self.changeFilter(6):

                self.filter_addition = str(int(self.ui.cuton_filter_6.value()))

                self.logger.info('Moving to %s nm Filter' % self.filter_addition)

                start_f6 = self.ui.scan_startNM_6.value()
                stop_f6 = self.ui.scan_stopNM_6.value()
                step_f6 = self.ui.scan_stepNM_6.value()
                amp_f6 = self.ui.scan_pickAmp_6.value()

                self.amplification = amp_f6
                self.LockinUpdateParameters()
                self.MonoHandleSpeedButton()

                scan_list = self.createScanJob(start_f6, stop_f6, step_f6)
                self.HandleMeasurement(scan_list, start_f6, stop_f6, step_f6, amp_f6, 3)

        self.changeFilter(1) 
        self.logger.info('Moving to open filter')               
        self.chooseFilter(1)
        self.complete_scan = False   
        self.ui.imageCompleteScan_start.setPixmap(QtGui.QPixmap("Button_on.png"))     
        self.logger.info('Finished Measurement') 

    # General function to create scanning list
        
    def createScanJob(self, start, stop, step):
        """Function to compile scan parameters 
        :param start: Wavelength start value
        :type start: float, required
        :param stop: Wavelength stop value
        :type stop: float, required
        :param step: Wavelength step value
        :type step: float, required
        ...
        :return: List of integer wavelength values
        """
        scan_list = []       
        number = int((stop-start)/step)
        
        for n in range(-1, number + 1): # -1 to start from before the beginning, +1 to include the last iteration of 'number', [and +2 to go above stop (this can be changed later])
            wavelength = start + n*step
            scan_list.append(wavelength)
            
        return scan_list
           
    # Scan through wavelength range   ### Not being used currently
           
    def Scan(self, scan_list):
        """Function to send commmands to monochromator and move through wavelength list
        :param scan_list: List of wavelength values to scan
        :type scan_list: list of ints, required
        ...
        :raises LoggerError: Raises error if second filter wheel not connected
        ...
        :return: None
        """
        if self.mono_connected:
            for element in scan_list:
                self.p.write('{:.2f} GOTO\r'.format(element).encode())
#                self.p.write('{:.2f} NM\r'.format(stop).encode())
                self.waitForOK()
                
        else:
            self.logger.error('Monochromator Not Connected')

        
# -----------------------------------------------------------------------------------------------------------        
    
    #### Functions to handle measurement

# -----------------------------------------------------------------------------------------------------------       
        
    # Measure LOCKIN response    
     
    def HandleMeasurement(self, scan_list, start, stop, step, amp, number):  
        """Function to prepare sample measurement
        :param scan_list: List of wavelength values to scan
        :type scan_list: list of ints, required
        :param start: Wavelength start value
        :type start: float, required
        :param stop: Wavelength stop value
        :type stop: float, required
        :param step: Wavelength step value
        :type step: float, required
        :param amp: Pre-amplifier amplification value
        :type amp: float, required
        :param number: Specifier to decide if power value is calculated (1) or not (0)
        :type number: int, required
        ...
        :return: None
        """      
        if self.mono_connected and self.lockin_connected and self.filter_connected:   
            # Assign user, expriment and file name for current measurement
            userName = self.ui.user.text()
            experimentName = self.ui.experiment.text()
            
            start_no = str(int(start))
            stop_no = str(int(stop))
            step_no = str(int(step))
            amp_no = str(int(amp))
            if number == 1:
#                name = 'Si_ref_diode'
                name = self.ui.file.text()  
            if number == 2:
#                name = 'InGaAs_ref_diode'
                name = self.ui.file.text()  
            if number == 3:
                name = self.ui.file.text()

            if not self.complete_scan: # If not a complete scan is taken
                fileName = name + '_(' + start_no + '-' + stop_no + 'nm_' + step_no + 'nm_' + amp_no + 'x)'
            elif self.complete_scan:
                fileName = name + '_' + self.filter_addition + 'Filter' + '_(' + start_no + '-' + stop_no + 'nm_' + step_no + 'nm_' + amp_no + 'x)' 
        
            #Set up path to save data
            self.path =f'{self.save_path}/{userName}/{experimentName}'
            self.logger.info(f'Saving data to: {self.path}')
            if not os.path.exists(self.path):
                os.makedirs(self.path)
            else:
                pass       
            self.naming(fileName, self.path, 2)  # This function defines a variable called self.file_name
            
            self.measure(scan_list, number)            
         
         
    def measure(self, scan_list, number):     
        """Function to perform sample measurement
        :param scan_list: List of wavelength values to scan
        :type scan_list: list of ints, required
        :param number: Specifier to decide if power value is calculated (1) or not (0)
        :type number: int, required
        ...
        :return: None
        """
#        columns = ['Wavelength', 'Mean Current', 'Amplification', 'Mean R', 'Log Mean R', 'Mean RMS', 'Mean X', 'Mean Y', 'Mean Frequency', 'Mean Phase']
        columns = ['Wavelength', 'Mean Current', 'Amplification', 'Mean R', 'Mean Frequency', 'Mean Phase']    
        
        self.measuring = True 
        self.ui.imageStop.setPixmap(QtGui.QPixmap("Button_off.png"))
        
        # Set up plot style                
        if self.do_plot:
#            plt.close()
            self.set_up_plot()
            
        time.sleep(1)

        # Set up empty lists for measurements
        plot_list_x = []
        plot_list_y = []
        plot_log_list_y = []
        plot_list_phase = []
        data_list = []
        data_df = pd.DataFrame(data_list, columns = columns) 
                    
        # Subscribe to scope
        self.path0 = '/' + self.device + '/demods/', self.c,'/sample'
        self.daq.subscribe(self.path0) 
        
        count = 0
        
#        self.chooseFilter(2)
        
        while len(scan_list)>0:            
            if self.measuring:                
                wavelength = scan_list[0]

                self.monoCheckFilter(wavelength)
                self.monoCheckGrating(wavelength)
                
                self.chooseWavelength(wavelength)
                
                # Poll data for 5 time constants, second parameter is poll timeout in [ms] (recomended value is 500ms) 
                dataDict = self.daq.poll(5*self.tc,500)  # Dictionary with ['timestamp']['x']['y']['frequency']['phase']['dio']['trigger']['auxin0']['auxin1']['time']
#                print(dataDict[self.device]['demods'][self.c]['sample']['timestamp'])
                
            
                # Recreate data
                if self.device in dataDict:
                    if dataDict[self.device]['demods'][self.c]['sample']['time']['dataloss']:
                        self.logger.info('Sample Loss Detected')
                    else:
                        if count>0: # Cut off the first measurement before the start to cut off the initial spike in the spectrum                         
#                           if self.imp50==0:     #### FIX THIS TO HANDLE IMP 50
#                                e = amp_coeff*amplitude/sqrt(2)
#                           elif self.imp50==1:  # If 50 Ohm impedance is enabled, the signal is cut in half
#                                e = 0.5*amp_coeff*amplitude/sqrt(2) 
                            
                            data = dataDict[self.device]['demods'][self.c]['sample']
                            rdata = sqrt(data['x']**2+data['y']**2)
                            rms = sqrt(0.5*(data['x']**2+data['y']**2))
                            current = rdata/self.amplification
                            
                            mean_curr = mean(current)
                            mean_r = mean(rdata)
                            log_mean_r = log(mean_r)
                            mean_rms = mean(rms)
                            mean_x = mean(data['x'])
                            mean_y = mean(data['y'])
                            mean_freq = mean(data['frequency'])
                            mean_phase = mean(data['phase'])
                                                                                         
                            
#                            scanValues = [wavelength, mean_curr, self.amplification, mean_r, log_mean_r, mean_rms, mean_x, mean_y, mean_freq, mean_phase]
                            scanValues = [wavelength, mean_curr, self.amplification, mean_r, mean_freq, mean_phase]
                           
                            plot_list_x.append(wavelength)
                            plot_list_y.append(mean_r)
                            plot_log_list_y.append(log_mean_r)
                            plot_list_phase.append(mean_phase)
        
                            data_list.append(scanValues)
                            
                            data_df = pd.DataFrame(data_list, columns = columns)
                            
                            if number == 1:
                                self.calculatePower(data_df, self.Si_cal)
                            elif number == 2:
                                self.calculatePower(data_df, self.InGaAs_cal)
                            else: #### CHECK THAT THIS WORKS!!!
                                pass
                            
                            data_file = data_df.to_csv(os.path.join(self.path, self.file_name))
                            
                            if self.do_plot:
                                self.ax1.plot(plot_list_x, plot_list_y, color = '#000000')
                                self.ax2.plot(plot_list_x, plot_log_list_y, color = '#000000')
                                self.ax3.plot(plot_list_x, plot_list_phase, color = '#000000')
                                plt.draw()
                                plt.pause(0.0001)
                                    
                del scan_list[0]
                count+=1  
                
            else:
                break
        
        # Unsubscribe to scope 
        self.daq.unsubscribe(self.path0)        

# -----------------------------------------------------------------------------------------------------------   

    # Function to calculate the reference power

    def calculatePower(self, ref_df, cal_df):
        """Function to calculate power
        :param ref_df: DataFrame of reference measurements
        :type ref_df: DataFrame, required
        :param cal_df: DataFrame of reference calibration measurements
        :type cal_df: DataFrame, required
        ...
        :return: DataFrame of reference diode measurements incl. power
        :rtype: DataFrame
        """        
        cal_wave_dict = {} # Create an empty dictionary
        power = [] # Create an empty list
            
        for x in range(len(cal_df['Wavelength [nm]'])): # Iterate through columns of calibration file
            cal_wave_dict[cal_df['Wavelength [nm]'][x]] = cal_df['Responsivity [A/W]'][x] # Add wavelength and corresponding responsivity to dictionary


        for y in range(len(ref_df['Wavelength'])): # Iterate through columns of reference file
#            print(ref_df['Wavelength'][y])
            if ref_df['Wavelength'][y] in cal_wave_dict.keys(): # Check if reference wavelength is in calibraton file
                power.append(float(ref_df['Mean Current'][y]) / float(cal_wave_dict[ref_df['Wavelength'][y]])) # Add power to the list
            else: # If reference wavelength is not in calibration file
                resp_int = self.interpolate(ref_df['Wavelength'][y], cal_df['Wavelength [nm]'], cal_df['Responsivity [A/W]']) # Interpolate responsivity
                power.append(float(ref_df['Mean Current'][y]) / float(resp_int)) # Add power to the list                
                
        ref_df['Power'] = power # Create new column in reference file
        
        return ref_df['Power']        
    
    # Function to interpolate values    
        
    def interpolate(self, num, x, y):     
        f = interp1d(x, y)
        return f(num)
        
# -----------------------------------------------------------------------------------------------------------   
            
    def set_up_plot(self): 
        """Function to set up plot
        :return: None
        """               
        style.use('ggplot')
        fig1 = plt.figure()
                    
        self.ax1 = fig1.add_subplot(3,1,1)
#        plt.xlabel('Time (s)', fontsize=17, fontweight='medium')
        plt.ylabel('R component (V)', fontsize=17, fontweight='medium')              
        plt.grid(True)
#        plt.box()
        plt.title('Demodulator data', fontsize=17, fontweight='medium')
        plt.tick_params(labelsize=14)
        plt.minorticks_on()
        plt.rcParams['figure.facecolor']='white'
        plt.rcParams['figure.edgecolor']='white'
        plt.tick_params(labelsize=15, direction='in', axis='both', which='major', length=8, width=2)
        plt.tick_params(labelsize=15, direction='in', axis='both', which='minor', length=4, width=2)

        self.ax2 = fig1.add_subplot(3,1,2)
#        plt.xlabel('Time (s)', fontsize=17, fontweight='medium')
        plt.ylabel('Log(R)', fontsize=17, fontweight='medium')              
        plt.grid(True)
#        plt.box()
        plt.tick_params(labelsize=14)
        plt.minorticks_on()
        plt.rcParams['figure.facecolor']='white'
        plt.rcParams['figure.edgecolor']='white'
        plt.tick_params(labelsize=15, direction='in', axis='both', which='major', length=8, width=2)
        plt.tick_params(labelsize=15, direction='in', axis='both', which='minor', length=4, width=2)
        
        self.ax3 = fig1.add_subplot(3,1,3)
        plt.xlabel('Wavelength [nm]', fontsize=17, fontweight='medium')
        plt.ylabel('Phase', fontsize=17, fontweight='medium') 
        plt.grid(True)
#        plt.box()
#        plt.title('Demodulator data', fontsize=17, fontweight='medium')
        plt.tick_params(labelsize=14)
        plt.minorticks_on()
        plt.rcParams['figure.facecolor']='white'
        plt.rcParams['figure.edgecolor']='white'
        plt.tick_params(labelsize=15, direction='in', axis='both', which='major', length=8, width=2)
        plt.tick_params(labelsize=15, direction='in', axis='both', which='minor', length=4, width=2)
        
#        plt.rcParams['font.family']='sans-serif'
#        plt.rcParams['font.sans-serif']='Times'   
        
#        plt.show()

# -----------------------------------------------------------------------------------------------------------   
        
    def naming(self, file_name, path_name, num):
        """Function to compile filename
        :param file_name: File name
        :type file_name: str, required
        :param path_name: Path name
        :type path_name: str, required
        :param num: Filter number
        :type num: str, required
        ...
        :return: None
        """        
        name = os.path.join(path_name, file_name)
        exists = os.path.exists(name)
        
        if exists:
            if num ==2:
                filename = file_name + '_%d' % num
            else:
                filename = file_name[:-1] + str(num)
            num += 1
            self.naming(filename, path_name, num)
        else:
            self.file_name = file_name

# -----------------------------------------------------------------------------------------------------------   
        
    def HandleStopButton(self):
        """Function to stop measurement
        :return: None
        """
        self.measuring = False
        self.ui.imageStop.setPixmap(QtGui.QPixmap("Button_on.png"))

    def HandleStopCompleteScanButton(self):
        """Function to stop multi-filter measurement
        :return: None
        """
        self.measuring = False
        self.ui.imageCompleteScan_stop.setPixmap(QtGui.QPixmap("Button_on.png"))

# -----------------------------------------------------------------------------------------------------------

    def get_logger(self):
        """Function to set up logger
        :return: Returns logger
        """
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                                      datefmt="%Y-%m-%d - %H:%M:%S")
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG)
        console.setFormatter(formatter)
    
#        logfile = logging.FileHandler('run.log', 'w')
#        logfile.setLevel(logging.DEBUG)
#        logfile.setFormatter(formatter)
    
        logger.addHandler(console)
#        logger.addHandler(logfile)
    
        return logger

# -----------------------------------------------------------------------------------------------------------
        
def main():

  app = QtWidgets.QApplication(sys.argv)
  monoUI = MainWindow()
  monoUI.show()
  sys.exit(app.exec_())

if __name__ == "__main__": 
  main()
  

