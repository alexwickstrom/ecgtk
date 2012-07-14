from __future__ import division
import scipy
import scipy.signal
import pylab
import datetime
# Running the tests
# run from a terminal "nosetests -v --with-doctest ecgtk.py"


def _norm_dot_product(a,b):
    """Will return normalized dot product for two vectors"""
    # TODO: Needs better documentation
    anorm = a/(scipy.dot(a,a)**0.5)
    bnorm = b/(scipy.dot(b,b)**0.5)
    return scipy.dot(anorm,bnorm)

def _ms_to_samples(ms, samplingrate):
    """convert interval in ms to number of samples.
    samplingrate is samples / second
    >>> _ms_to_samples(500, 1000)
    500
    >>> _ms_to_samples(100, 500)
    50"""
    return int(samplingrate * ms / 1000)

def _samples_to_ms(samples, samplingrate):
    """convert an interval in samples to
    time in ms. samplingrate is samples/second.
    >>> _samples_to_ms(500, 1000)
    500
    >>> _samples_to_ms(50, 500)
    100
    """
    return int(samples * 1000 / samplingrate)

def _format_time_wfdb(ms):
    """convert time in ms to format compatible with rdann.
    This is in the form (hh):mm:ss.sss
    >>> _format_time_wfdb(7322002)
    '02:02:02.002'
    """
    hr, minute = ms//3600000 % 24, ms//60000 % 60
    sec, ms = ms//1000 % 60, ms % 1000
    timeobj = datetime.time(hr, minute, sec, ms*1000) # last val is microsecs
    return timeobj.isoformat()[:-3] # back to ms

def _lfilter_zi(b,a):
    #compute the zi state from the filter parameters. 
    #Based on:
    # Fredrik Gustafsson, Determining the initial states in forward-backward 
    # filtering, IEEE Transactions on Signal Processing, pp. 988--992, April 1996, 
    # Volume 44, Issue 4
    n=max(len(a),len(b))
    zin = (scipy.eye(n-1) - scipy.hstack( (-a[1:n,scipy.newaxis],
                                 scipy.vstack((scipy.eye(n-2), scipy.zeros(n-2))))))
    zid=  b[1:n] - a[1:n]*b[0]
    zi_matrix=scipy.linalg.inv(zin)*(scipy.matrix(zid).transpose())
    zi_return=[]
    #convert the result into a regular array (not a matrix)
    for i in range(len(zi_matrix)):
      zi_return.append(float(zi_matrix[i][0]))

    return scipy.array(zi_return)

def filtfilt(b,a,x):
    """
    Filter with given parameters forward and in reverse to eliminate
    phase shifts.
    In addition, initial state is calculated with lfilter_zi and 
    mirror images of the sample are added at end and beginning to
    remove edge effects.
    Must be a one-dimensional array only.
    """
    #For now only accepting 1d arrays
    ntaps=max(len(a),len(b))
    edge=ntaps*3

    if x.ndim != 1:
        raise ValueError, "Filtfilt is only accepting 1 dimension arrays."

    #x must be bigger than edge
    if x.size < edge:
        raise ValueError, "Input vector needs to be bigger than 3 * max(len(a),len(b)."

    if len(a) < ntaps:
        a=scipy.r_[a,scipy.zeros(len(b)-len(a))]

    if len(b) < ntaps:
        b=scipy.r_[b,scipy.zeros(len(a)-len(b))]

    zi=_lfilter_zi(b,a)

    #Grow the signal to have edges for stabilizing 
    #the filter with inverted replicas of the signal
    s=scipy.r_[2*x[0]-x[edge:1:-1],x,2*x[-1]-x[-1:-edge:-1]]
    #in the case of one go we only need one of the extrems 
    # both are needed for filtfilt

    (y,zf)=scipy.signal.lfilter(b,a,s,-1,zi*s[0])

    (y,zf)=scipy.signal.lfilter(b,a,scipy.flipud(y),-1,zi*y[-1])

    return scipy.flipud(y[edge-1:-edge+1])

def _rms(vector):
    """returns the root mean square
    >>> _rms(scipy.array([1,2,3,4,5]))
    3.3166247903553998
    """
    return scipy.sqrt(scipy.mean(vector**2))

def _zeropad(shortvec, l):
    """Pad the vector shortvec with terminal zeros to length l
    >>> _zeropad(scipy.array([1,2,3,4,5]), 10)
    array([1, 2, 3, 4, 5, 0, 0, 0, 0, 0])
    """
    return scipy.hstack((shortvec, scipy.zeros((l - len(shortvec)), dtype='int')))

def _write_ann(self, qrs_peaks, annfile):
    """Write an annotation file for the QRS onsets in a format
    that is usable with wrann. qrspeaks is in samples"""
    fi = open(annfile, 'w')
    for qrs in qrs_peaks:
        fi.write('%s '*5 + '%s\n' %(_format_time_wfdb(_sample_to_ms(qrs)),
                                    qrs, 'N', 0, 0, 0))
    fi.close()


class QRSDetector():
    """
    """
    def __init__(self, ecgdata, samplingrate=1000):
        """
        - 'ecgdata' : array - points x leads in case of multiple leads
                      or a vector in case of a single
        - 'samplingrate' : samples per second, default 1000
        """
        try:
            self.data = scipy.array(ecgdata, dtype='float')
        except ValueError, msg:
            raise ValueError("Invalid format for ecg data - %s" %(msg))
            
        self.samplingrate = samplingrate

        # convert vector to column array
        if len(self.data.shape) == 1:
            self.data = scipy.array([self.data]).transpose()

        self.points, self.leads = self.data.shape
        if len(self.data.shape) > 1 and self.leads > self.points:
            raise ValueError("ECG data has more columns than rows")

        # we need atleast 8 seconds of data (for initializing buffers)
        if self.points < self.samplingrate * 8:
            raise ValueError("Length of ECG is less than 8 seconds")
        
        
    def qrs_detect(self, qrslead=0):
         """Detect QRS onsets using modified PT algorithm
         """
         # If ecg is a vector, it will be used for qrs detection.
         # If it is a matrix, use qrslead (default 0)
         if len(self.data.shape) == 1:
             self.raw_ecg = self.data
         else:
             self.raw_ecg = self.data[:,qrslead]

         # butterworth bandpass filter 5 - 15 Hz
         self.filtered_ecg = self._bpfilter(self.raw_ecg)
         # differentiate
         self.diff_ecg  = scipy.diff(self.filtered_ecg)
         # take absolute value (was square in original PT implementation)
         self.abs_ecg = abs(self.diff_ecg)
         # integrate 
         self.int_ecg = self._mw_integrate(self.abs_ecg)
         
         # Construct buffers with last 8 values 
         self._initializeBuffers(self.int_ecg)

         # collect all unique local peaks in the integrated ecg
         peaks = self.peakDetect(self.int_ecg)

         # classify each peak as QRS or noise
         self.checkPeaks(peaks, self.int_ecg)


         # compensate for delay during integration
         self.QRSpeaks -= 40 * (self.samplingrate / 1000)
         
         return self.QRSpeaks

    def qrs_detect_multiple_leads(self, leads=[]):
        """Use multiple leads for qrs detection.
        Leads to use may be given as list of lead indices.
        Default is to use all leads"""
        # leads not specified, switch to all leads
        if leads == []:
            leads = range(self.leads)

        # qrs detection for each lead
        qrspeaks = []
        for lead in leads:
            qrspeaks.append(self.qrs_detect(lead))

        # DEBUG
        print "length of qrs in different channels"
        print [len(x) for x in qrspeaks]

        # zero pad detections to match lengths
        maxlength = max([len(qrspeak_lead) for qrspeak_lead in
                         qrspeaks])
        for lead in range(len(qrspeaks)):
            qrspeaks[lead] = self._zeropad(qrspeaks[lead], maxlength)

        #DEBUG
        print "max length ", maxlength
        print [len(x) for x in qrspeaks]
        
        qrspeaks_array = scipy.array(qrspeaks).transpose()
        self.QRSpeaks = self.multilead_peak_match(qrspeaks_array)
        return self.QRSpeaks

    def _zeropad(self, shortvec, l):
        """Pad the vector shortvec with terminal zeros to length l"""
        return scipy.hstack((shortvec, scipy.zeros((l - len(shortvec)), dtype='int')))
        
    def write_ann(self, annfile):
        """Write an annotation file for the QRS onsets in a format
        that is usable with wrann"""
        fi = open(annfile, 'w')
        for qrspeak in self.QRSpeaks:
            fi.write('%s %s %s %s %s %s\n' %(self._sample_to_time(qrspeak), qrspeak, 'N', 0, 0, 0))
        fi.close()

    def _sample_to_time(self, sample):
        """convert from sample number to a string representing
        time in a format required for the annotation file.
        This is in the form (hh):mm:ss.sss"""
        time_ms = int(sample*1000 / self.samplingrate)
        hr, min, sec, ms = time_ms//3600000 % 24, time_ms//60000 % 60, \
                           time_ms//1000 % 60, time_ms % 1000
        timeobj = datetime.time(hr, min, sec, ms*1000) # last val is microsecs
        return timeobj.isoformat()[:-3] # back to ms
         
    def visualize_qrs_detection(self, savefilename = False):
        """Plot the ecg at various steps of processing for qrs detection.
        Will not plot more than 10 seconds of data.
        If filename is input, image will be saved"""
        ecglength = len(self.raw_ecg)
        ten_seconds = 10 * self.samplingrate
        
        if ecglength > ten_seconds:
            segmentend = ten_seconds
        elif ecglength < ten_seconds:
            segmentend = ecglength

        segmentQRSpeaks = [peak for peak in self.QRSpeaks if peak < segmentend]

        pylab.figure()
        pylab.subplot(611)
        pylab.plot(self.raw_ecg[:segmentend])
        pylab.ylabel('Raw ECG', rotation='horizontal')
        pylab.subplot(612)
        pylab.plot(self.filtered_ecg[:segmentend])
        pylab.ylabel('Filtered ECG',rotation='horizontal')
        pylab.subplot(613)
        pylab.plot(self.diff_ecg[:segmentend])
        pylab.ylabel('Differential',rotation='horizontal')
        pylab.subplot(614)
        pylab.plot(self.abs_ecg[:segmentend])
        pylab.ylabel('Squared differential',rotation='horizontal')
        pylab.subplot(615)
        pylab.plot(self.int_ecg[:segmentend])
        pylab.ylabel('Integrated', rotation='horizontal')
        pylab.subplot(616)
        pylab.hold(True)
        pylab.plot(self.raw_ecg[:segmentend])
        pylab.plot(segmentQRSpeaks, self.raw_ecg[segmentQRSpeaks], 'xr')
        pylab.hold(False)
        pylab.ylabel('QRS peaks', rotation='horizontal')

        if savefilename:
            pylab.savefig(savefilename)
        else:
            pylab.show()
        
    def _initializeBuffers(self, ecg):
        """Initialize the 8 beats buffers using values
        from the first 8 one second intervals        
        """
        onesec = self.samplingrate
        # signal peaks are peaks in the 8 segments
        self.signal_peak_buffer = [max(ecg[start*onesec:(start+1)*onesec])
                                                  for start in range(8)]
        self.noise_peak_buffer = [0] * 8
        self.rr_buffer = [1] * 8
        self._updateThreshold()
        
    def _updateThreshold(self):
        """Calculate threshold based on amplitudes of last
        8 signal and noise peaks"""
        noise = scipy.mean(self.noise_peak_buffer)
        signal = scipy.mean(self.signal_peak_buffer)
        self.threshold = noise + 0.3125 * (signal - noise)

    def peakDetect(self, ecg):
        """Determine local maxima that are larger than others in
        adjacent 200
        """
        # list all local maxima
        peak_indices = [i for i in range(1,len(ecg)-1)
                     if ecg[i-1] < ecg[i] > ecg[i+1]]
        peak_amplitudes = [ecg[peak] for peak in peak_indices]

        # restrict to peaks that are larger than anything else 200 ms
        # on either side
        unique_peaks = []
        minimumRR = self.samplingrate * 0.2

        # start with first peak
        peak_candidate_index = peak_indices[0]
        peak_candidate_amplitude = peak_amplitudes[0]

        # test successively against other peaks
        for peak_index, peak_amplitude in zip(peak_indices, peak_amplitudes):
            # if new peak is less than minimumRR away and is larger,
            # it becomes candidate
            if peak_index - peak_candidate_index <= minimumRR and\
                                  peak_amplitude > peak_candidate_amplitude:
                peak_candidate_index = peak_index
                peak_candidate_amplitude = peak_amplitude

            # if new peak is more than 200 ms away, candidate is promoted to
            # a unique peak and new peak becomes candidate
            elif peak_index - peak_candidate_index > minimumRR:
                unique_peaks.append(peak_candidate_index)
                peak_candidate_index = peak_index
                peak_candidate_amplitude = peak_amplitude

            else:
                pass

        return unique_peaks


    def checkPeaks(self, peaks, ecg):
        """Check the given peaks one by one according to
        thresholds that are constantly updated"""
        #amplitudes = [ecg[peak] for peak in peaks]
        self.QRSpeaks = [0] # will remove zero later
        
        # augment the peak list with the last point of the ecg
        peaks += [len(ecg)-1]
        
        for index in range(len(peaks)-1):
            peak = peaks[index]
            amplitude = ecg[peak]
            amp_ratio = amplitude / self.threshold
            # accept as QRS if larger than threshold
            # slope in raw signal +-30% of previous slopes - not implemented
            if amp_ratio > 1:
                self.acceptasQRS(peak, amplitude)

            # reject if less than half threshold
            elif amp_ratio < 0.5:
                self.acceptasNoise(peak, amplitude)
                
            # acccept as qrs if higher than half threshold,
            # but is 360 ms after last qrs and
            # next peak is more than 1.5 rr intervals away
            # just abandon it if there is no peak before or after
            else:
                meanrr = scipy.mean(self.rr_buffer)
                lastQRS_to_this_peak = (peak - self.QRSpeaks[-1]) / self.samplingrate
                lastQRS_to_next_peak = peaks[index+1] - self.QRSpeaks[-1]

                if lastQRS_to_this_peak > 0.36 and lastQRS_to_next_peak > 1.5 * meanrr:
                    self.acceptasQRS(peak, amplitude)
                else:
                    self.acceptasNoise(peak, amplitude)

        self.QRSpeaks = scipy.array(self.QRSpeaks[1:])
        return

    def acceptasQRS(self, peak, amplitude):
        self.QRSpeaks.append(peak)

        self.signal_peak_buffer.pop(0)
        self.signal_peak_buffer.append(amplitude)

        if len(self.QRSpeaks) > 1:
            self.rr_buffer.pop(0)
            self.rr_buffer.append(self.QRSpeaks[-1] - self.QRSpeaks[-2])


    def acceptasNoise(self, peak, amplitude):
        self.noise_peak_buffer.pop(0)
        self.noise_peak_buffer.append(amplitude)
            
    def _mw_integrate(self, ecg):
        """
        Integrate the ECG signal over a defined
        time period. 
        """
        # window of 80 ms - better than using a wider window
        window_length = int(80 * (self.samplingrate / 1000))
        int_ecg = scipy.zeros_like(ecg)
        cs = ecg.cumsum()
        int_ecg[window_length:] = (cs[window_length:] -
                                   cs[:-window_length]) / window_length
        int_ecg[:window_length] = cs[:window_length] / scipy.arange(
                                                   1, window_length + 1)
        return int_ecg

    def _bpfilter(self, ecg):
         """Bandpass filter the ECG with a bandpass setting of
         5 to 15 Hz"""
         # relatively basic implementation for now
         Nyq = self.samplingrate / 2
         wn = [5/ Nyq, 15 / Nyq]
         b,a = scipy.signal.butter(2, wn, btype = 'bandpass')
         # TODO: filtfilt should be implemented here
         return ecgtools.basic_tools.filtfilt(b,a,ecg)

    def multilead_peak_match(self, peaks):
        """Reconcile QRS detections from multiple leads.
        peaks is a matrix of peak_times x leads.
        If the number of rows is different,
        pad shorter series with zeros at end"""
        ms90 = 90 * self.samplingrate / 1000
        Npeaks, Nleads = peaks.shape
        current_peak = 0
        unique_peaks = []

        while current_peak < len(peaks):
            all_values = peaks[current_peak, :]
            outer = all_values.max()
            outerlead = all_values.argmax()
            inner = all_values.min()
            innerlead = all_values.argmin()

            #
            near_inner = sum(all_values < inner + ms90)
            near_outer = sum(all_values > outer - ms90)

            #all are within 90 ms
            if near_inner == near_outer == Nleads:
                unique_peaks.append(int(scipy.median(all_values)))
                current_peak += 1

            # max is wrong
            elif near_inner > near_outer:
                peaks[current_peak+1:Npeaks, outerlead] = peaks[current_peak:Npeaks-1, outerlead]
                peaks[current_peak, outerlead] = scipy.median(all_values)
                # do not change current peak now

            # min is wrong
            elif near_inner <= near_outer:
                peaks[current_peak:Npeaks-1, innerlead] = peaks[current_peak+1:Npeaks, innerlead]
                peaks[-1, innerlead] = 0

        return unique_peaks


    
class ECG():
    def __init__(self, data, info = {'samplingrate': 1000}):
        """
        data is a numpy matrix, either single column or multiple
        info is a dict
        units should be in mv
        """
        self.data = data
        self.samplingrate = info['samplingrate']
        self.qrsonsets = None

    def remove_baseline(self, anchorx, window):
        """
        Remove baseline wander by subtracting a cubic spline.
        anchorx is a vector of isoelectric points (usually qrs onset -20ms)
        window is width of window to use (in ms) for averaging the amplitude at anchors
        """
        for chan in self.data.shape[1]:
            ecg = self.data[:,chan]
            windowwidth = _ms_to_samples(window, self.samplingrate) / 2
            #Do we have enough points before first anchor to use it
            if anchorx[0] < windowwidth:
                anchorx = anchorx[1:]
            # subtract dc
            ecg -= scipy.mean(ecg[anchorx[:]]) 
            # amplitudes for anchors
            # window is zero, no averaging
            if windowwidth == 0:
                anchory = scipy.array([ecg[x] for x in anchorx])
            # or average around the anchor
            else:
                anchory = scipy.array([scipy.mean(ecg[x-windowwidth:x+windowwidth])
            for x in anchorx])
            # x values for spline that we are going to calculate
            splinex = scipy.array(range(len(ecg)))
            # calculate cubic spline fit
            tck = scipy.interpolate.splrep(anchorx, anchory)
            spliney = scipy.interpolate.splev(splinex, tck)
            # subtract the spline
            ecg -= spliney

        self.data[:, chan] = ecg


    def get_qrsonsets(self, qrslead):
        """
        Using pan tomkins method detect qrs onsets
        currently only qrs peak is detected
        """
        det = QRSDetector(self.data[:, qrslead], self.info['samplingrate'])
        self.qrsonsets = det.qrs_detect()


    def write_ann(self, annfile):
        """Write an annotation file for the QRS onsets in a format
        that is usable with wrann"""
        fi = open(annfile, 'w')
        for qrspeak in self.QRSpeaks:
            fi.write('%s '*4 + '%s\n' %(self._sample_to_time(qrspeak), qrspeak, 'N', 0, 0, 0))
        fi.close()


    def drawECG(self, start=0, leads=range(12), savefilename=None):
        """
        Draw a 12 lead ECG with background grid 
        start is time of recording to start from in seconds
        first 12 leads are used by default, else leads can be specified
        If savefilename is not given, ecg will be plotted
        """
        if self.data.shape[1] < 12:
            raise ValueError, 'Less than 12 leads available'
        if self.data.shape[0] / self.samplingrate < 10:
            raise ValueError, 'Less than 10 seconds of data available'

        data = self.data[:, leads]

        ################################################################################
        #
        #    Draw the background    
        #
        ################################################################################

        #time scale  - 1  ms/px  (1mm = 40 px at 25 mm/s)
        #amp scale -  2.5 mcV/px (1mm = 40 px at 100 mcv/mm) 
        #image width = 10 seconds = 10000 px
        #image height = 4 strips
        #strip height = 34 mm (3.4 mV)
        
        onemm = 40 * int(self.samplingrate / 1000)
        onesec = self.samplingrate
        onemv = 400 / 1000 # correct for microV
        lenecg = 10*onesec
        htecg = 136*onemm

        #Linethicknesses
        thickbgwidth = 0.4
        thinbgwidth = 0.1
        ecgwidth = 0.8

        pylab.figure()
        #thick horizontal lines
        for horiz in range(0,htecg,5*onemm):
            pylab.plot([0,lenecg],[horiz,horiz],'r',linewidth=thickbgwidth)

        #thick vertical lines
        for vert in range(0,lenecg,5*onemm):
            pylab.plot([vert,vert],[0,htecg],'r',linewidth=thickbgwidth)

        #thin horizontal lines
        for horiz in range(0,htecg,onemm):
            pylab.plot([0,lenecg],[horiz,horiz],'r',linewidth=thinbgwidth)

        #thin vertical lines
        for vert in range(0,lenecg,onemm):
            pylab.plot([vert,vert],[0,htecg],'r',linewidth=thinbgwidth)
            
        ################################################################################
        #
        #    Draw the ECG    
        #
        ################################################################################
        startplot = 0
        stripcenter = 17 #in mm
        striplength = int(62.5*onemm) # in px (2.5 seconds)
        rhythmlead = 1

        horizcenters = (((scipy.array([0,-1,-2,-3]))*2*stripcenter) - 17) *onemm

        #prepare data
        for lead in range(12):
            #center horizontally
            data[:,lead] -= scipy.mean(data[:,lead])
        #rescale    
        data *= onemv    

        #column 1
        for lead in range(3):
            pylab.plot(range(striplength),\
                       data[startplot:striplength+startplot,lead]-horizcenters[3-lead],\
                       'k',linewidth = ecgwidth)

        #column 2
        for lead in range(3,6):
            pylab.plot(range(striplength,2*striplength),\
                       data[striplength+startplot:striplength*2+startplot,lead]-horizcenters[6-lead],\
                       'k',linewidth = ecgwidth)
            
        #column 3
        for lead in range(6,9):
            pylab.plot(range(2*striplength,3*striplength),\
                       data[striplength*2+startplot:striplength*3+startplot,lead]-horizcenters[9-lead],\
                       'k',linewidth = ecgwidth)

        #column 4
        for lead in range(9,12):
            pylab.plot(range(3*striplength,4*striplength),\
                       data[striplength*3+startplot:striplength*4+startplot,lead]-horizcenters[12-lead],\
                       'k',linewidth = ecgwidth)

        #rhythm strip
        pylab.plot(range(4*striplength),\
                   data[startplot:4*striplength,rhythmlead]-horizcenters[0],\
                   'k',linewidth = ecgwidth)

        ################################################################################
        #
        #    Labels
        #
        ################################################################################
        labels = ['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']
        xoffset = 20
        yoffset = -250
        labelx = [xoffset]*3               +    [xoffset+striplength]*3 +\
                 [xoffset+2*striplength]*3 +    [xoffset+3*striplength]*3
        labely = list(yoffset - horizcenters[3:0:-1])*4

        for labelct in range(12):
            pylab.text(labelx[labelct],labely[labelct],labels[labelct],fontsize=8)

        pylab.text(labelx[0],yoffset-horizcenters[0],labels[rhythmlead],fontsize=8)

        #pylab.axis('off')
        pylab.setp(pylab.gca(),xticklabels=[])
        pylab.setp(pylab.gca(),yticklabels=[])
        pylab.axis([0,lenecg,0,htecg])
        
        if not savefilename:
            pylab.show()
        else:
            pylab.savefig(savefilename, dpi=300)
            
            #if possible, crop with imagemagick
            try:
                commands.getoutput("mogrify -trim '%s'" %(savefilename))
            except:
                pass



def test_remove_baseline():
    """test for remove_baseline function
    """
    testsignal = scipy.sin(scipy.arange(0,2*scipy.pi,0.01))

    npoints = len(testsignal)
    anchors = range(0,len(testsignal), len(testsignal)//8)
    window = 0

    ecg = ECG(testsignal, 1)
    rms_with_baseline = _rms(ecg.ecg)
    ecg.remove_baseline(anchors, window)
    rms_without_baseline = _rms(ecg.ecg)
    assert rms_without_baseline / rms_with_baseline < 0.01

if __name__ == '__main__':
    pass
