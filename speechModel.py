from __future__ import division

import re
import sys
import json
from google.oauth2 import service_account
from google.auth.credentials import Credentials
from google.cloud import speech

import pyaudio
from six.moves import queue

import google.cloud.texttospeech as tts

from pydub import AudioSegment
from pydub.playback import play

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms
keyfile_dict = json.loads(open('baraboo.json').read())
credentials = service_account.Credentials.from_service_account_info(keyfile_dict)
credentials_tts = service_account.Credentials.from_service_account_info(json.loads(open('baraboo839-197edc827eca.json').read()))

class MicrophoneStream(object):
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream, into the buffer."""
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)


def listen_print_loop(responses, pipe):
    """Iterates through server responses and prints them.

    The responses passed is a generator that will block until a response
    is provided by the server.

    Each response may contain multiple results, and each result may contain
    multiple alternatives; for details, see https://goo.gl/tjCPAU.  Here we
    print only the transcription for the top alternative of the top result.

    In this case, responses are provided for interim results as well. If the
    response is an interim one, print a line feed at the end of it, to allow
    the next result to overwrite it, until the response is a final one. For the
    final one, print a newline to preserve the finalized transcription.
    """
    num_chars_printed = 0
    #print(num_chars_printed)
    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        # Display the transcription of the top alternative.
        transcript = result.alternatives[0].transcript
        #print(transcript, "transcript")

        # Display interim results, but with a carriage return at the end of the
        # line, so subsequent lines will overwrite them.
        #
        # If the previous result was longer than this one, we need to print
        # some extra spaces to overwrite the previous result
        overwrite_chars = " " * (num_chars_printed - len(transcript))
        if pipe.poll() and pipe.recv() == "Exit":
            print("Exiting speech process")
            return

        if not result.is_final:
            if re.search(r"\b(Baraboo)\b", transcript, re.I):
                sys.stdout.write(transcript + overwrite_chars + "\r")
                sys.stdout.flush()

            num_chars_printed = len(transcript)

        else:
            # print("final after quit:"+transcript + overwrite_chars)
            pipe.send(transcript)

            # Exit recognition if any of the transcribed phrases could be
            # one of our keywords.

            num_chars_printed = 0


def speechMain(pipe):

    # See http://g.co/cloud/speech/docs/languages
    # for a list of supported languages.
    language_code = "en-US"  # a BCP-47 language tag

    client = speech.SpeechClient(credentials=credentials)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config, interim_results=True
    )
    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )
        print("I'm starting up. Please wait")
        text_to_wav("en-US-News-K","Give me a minute to start up?")
        responses = client.streaming_recognize(streaming_config, requests)
        print("I'm Ready!")
        text_to_wav("en-US-News-K","I'm Ready!")
        # Now, put the transcription responses to use.
        listen_print_loop(responses, pipe)


def text_to_wav(voice_name: str, text: str):
    language_code = "-".join(voice_name.split("-")[:2])
    text_input = tts.SynthesisInput(text=text)
    voice_params = tts.VoiceSelectionParams(
        language_code=language_code, name=voice_name
    )
    audio_config = tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16)

    client = tts.TextToSpeechClient(credentials=credentials_tts)
    response = client.synthesize_speech(
        input=text_input,
        voice=voice_params,
        audio_config=audio_config,
    )
    filename = f"{voice_name}.wav"
    with open(filename, "wb") as out:
        out.write(response.audio_content)
        #print(f'Generated speech saved to "{filename}"')
    #filename = f"{voice_name}.wav"

    song = AudioSegment.from_wav(filename)
    play(song)