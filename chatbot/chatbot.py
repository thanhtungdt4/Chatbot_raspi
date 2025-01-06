import socket
import subprocess
import threading
import time
import sqlite3
import random
import os
import json
import psutil
import speech_recognition as sr

from fuzzywuzzy import fuzz, process
from gtts import gTTS
from pytube import Search


class ChatBot:
    """
    ChatBot class
    """
    def __init__(self, chatbot_dir="/home/pi/workspace/chatbot"):
        self.chatbot_dir = chatbot_dir
        self.json_file_path = f"{self.chatbot_dir}/data/options.json"
        self.recognizer = sr.Recognizer()
        self.conn = self.init_db()
        self.story_options = self.load_options_from_json("story")
        self.enter_youtube_options = self.load_options_from_json("enter_youtube")
        self.exit_youtube_options = self.load_options_from_json("exit_youtube")
        self.stop_video_options = self.load_options_from_json("stop_video")
        self.voice_dict = self.parse_json_to_dict("Other")

    def change_volume(self, step=10, increase=True):
        """
        Changes the system volume by the specified step percentage.

        Args:
            step (int): The percentage to change the volume by (default is 10).
            increase (bool): True to increase the volume, False to decrease.
        Returns:
            bool: True if the volume was changed successfully, False otherwise.
        """
        try:
            operation = "+" if increase else "-"
            command = f"amixer set Master {step}%{operation}"
            subprocess.run(command, shell=True, check=True)
            action = "increased" if increase else "decreased"
            print(f"Volume {action} by {step}%.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to change volume. {e}")
            return False

    def change_volume_by_voice(self, user_input, is_speak=True):
        """
        Use user voice to change volume.

        Args:
            user_input: User voice input.

        Returns:
            bool: True if a volume-related command was recognized and executed,
            else False.
        """
        catched = False
        if ("tăng âm" in user_input or "tăng volum" in user_input
                or "tăng volume" in user_input):
            if not self.change_volume():
                if is_speak:
                    self.speak(self.voice_dict["not_increased_vol"])
            else:
                if is_speak:
                    self.speak(self.voice_dict["increased_vol"])
            catched = True
        if ("giảm âm" in user_input or "giảm volum" in user_input
                or "giảm volume" in user_input):
            if not self.change_volume(increase=False):
                if is_speak:
                    self.speak(self.voice_dict["not_decreased_vol"])
            else:
                if is_speak:
                    self.speak(self.voice_dict["decreased_vol"])
            catched = True
        return catched

    def check_internet(self, host="8.8.8.8", port=53, timeout=5):
        """
        Checks if the network can access the internet.

        Returns:
            bool: True if internet is accessible, False otherwise.
        """
        try:
            socket.setdefaulttimeout(timeout)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
            return True
        except (socket.timeout, socket.error):
            return False

    def check_and_kill_process(self, process_name):
        """
        Checks if a process with the given name is running, and kills it if found.

        Args:
            process_name (str): The name of the process to check and kill.
        """
        for process in psutil.process_iter(attrs=["pid", "name"]):
            try:
                if process.info["name"] == process_name:
                    print(f"Process '{process_name}' found with PID "
                          f"{process.info['pid']}. Killing it.")
                    process.terminate()
                    process.wait(timeout=3)
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"Error handling process: {e}")
                continue

    def search_mp4(self, keyword):
        """
        Search for a video on YouTube using the given keyword and return the
        video URL.

        Args:
            keyword (str): The keyword to search for.

        Returns:
            str or None: The URL of the first video found, or None if no video
            is found.
        """
        try:
            search_results = Search(keyword)
            if search_results.results:
                return search_results.results[0].watch_url
            else:
                return None
        except Exception as e:
            print(f"An error occurred during the search: {e}")
            return None

    def play_video(self, video_url):
        """
        Streams and plays a video from a given URL using yt-dlp and mpv.

        Args:
            video_url (str): The URL of the video to be streamed and played.

        Returns:
            bool: True if the video was played successfully, False otherwise.
        """
        command = (f'yt-dlp -f "bestaudio[abr<=128]" -o - {video_url} | '
                   f'mpv --demuxer-lavf-o=buffer_size=1000000 -')
        try:
            subprocess.run(command, shell=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error occurred while playing the video: {e}")
            return False

    def listen_voice_in_thread(self, running, stop_video_options):
        """
        Starts a thread to listen for user voice commands and handle them in
        parallel.

        Args:
            running (list[bool]): A mutable list with a single boolean element
            to control the running state of the thread.
            stop_video_options (list[str]): A list of voice commands to stop
            video playback.

        Returns:
            threading.Thread: The thread object that was started.
        """
        thread = threading.Thread(
            target=self.listen_thread_handle,
            args=(running, stop_video_options),
            daemon=True
        )
        thread.start()
        return thread

    def listen_thread_handle(self, running, stop_video_options):
        """
        Listens for voice commands in a loop and performs actions based on the
        input.

        Args:
            running (list[bool]): A mutable list with a single boolean element
            to control the loop's execution.
            stop_video_options (list[str]): A list of voice commands that trigger
            stopping video playback.
        """
        while running[0]:
            user_input = self.listen()
            if user_input:
                if self.change_volume_by_voice(user_input):
                    continue
                match = self.get_best_match(user_input, stop_video_options)
                if match:
                    self.check_and_kill_process("mpv")
                    self.check_and_kill_process("yt-dlp")
                    break

    def no_internet_speak(self):
        """
        Plays a predefined audio file to notify the user of a lack of internet
        connectivity.

        Behavior:
            - Uses the `mpg123` command-line tool to play an MP3 file stored in
            the chatbot's data directory.
            - The audio file is expected to communicate that the system cannot
            connect to the internet.
        """
        os.system(f"mpg123 {self.chatbot_dir}/data/NoInternet.mp3")

    def speak(self, text):
        """
        Converts the input text to speech in Vietnamese and plays it.

        This function uses Google Text-to-Speech (gTTS) to generate an MP3 audio
        file from the input text in Vietnamese. The generated audio file is
        temporarily saved to "/tmp/temp_audio.mp3", and then played using the
        mpg123 command.

        Args:
            text (str): The text to be converted to speech.

        Returns:
            None
        """
        try:
            tts = gTTS(text=text, lang="vi")
            mp3_file = "/tmp/temp_audio.mp3"
            tts.save(mp3_file)
            os.system(f"mpg123 {mp3_file}")
        except Exception:
            self.no_internet_speak()

    def parse_json_to_dict(self, option):
        """
        Parses a JSON file containing 'Other' key with a list of dictionaries
        and returns a dictionary with key-value pairs from the list.

        Args:
            option (str): The key for which to retrieve options from the JSON
            file.

        Returns:
            dict: A dictionary containing the key-value pairs
        """
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            other_data = data.get(option, [])

            parsed_dict = {item_key: item_value for item in other_data for
                           item_key, item_value in item.items()}

            return parsed_dict

        except FileNotFoundError:
            print("Error: File not found.")
            return {}
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return {}

    def load_options_from_json(self, options):
        """
        Loads specific options from a JSON file.

        This function attempts to load a JSON file containing options from the
        specified directory (`self.chatbot_dir/data/options.json`). If the file
        is found and the JSON is valid, it retrieves the options corresponding to
        the given key. If any errors occur (e.g., file not found or invalid JSON),
        it handles them gracefully and returns an empty list.

        Args:
            options (str): The key for which to retrieve options from the JSON
            file.

        Returns:
            list: A list of options corresponding to the provided key. If the
                  file is not found or the JSON is invalid, an empty list is
                  returned.
        """
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data.get(options, [])
        except FileNotFoundError:
            print("Error: File not found.")
            return []
        except json.JSONDecodeError:
            print("Error: Invalid JSON format.")
            return []

    def get_best_match(self, query, options):
        """
        Finds the best matching option for a given query.

        This function uses the `fuzzywuzzy` library's `process.extractOne`
        method to find the closest match from a list of options based on the
        query string. If the best match has a score of 75 or higher, it is
        returned. If the score is lower than 75, `None` is returned.

        Args:
            query (str): The query string for which to find the best match.
            options (list): A list of strings to compare the query against.

        Returns:
            str or None: The best matching option if the score is 75 or higher,
                     or `None` if no suitable match is found.
        """
        best_match, score = process.extractOne(query, options)
        if score >= 75:
            return best_match
        return None

    def init_db(self):
        """
        Initializes the database and creates the necessary table.

        This function establishes a connection to an SQLite database located at
        `self.chatbot_dir/data/chatbot.db`. It then creates a table called
        `responses` if it does not already exist, with columns for `id`
        (automatically incremented), `question` (the question asked), and
        `answer` (the corresponding answer).

        Returns:
            sqlite3.Connection: A connection object to the SQLite database.
        """
        conn = sqlite3.connect(f"{self.chatbot_dir}/data/chatbot.db")
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        )
        """)
        conn.commit()
        return conn

    def get_response(self, user_input):
        """
        Retrieves the best matching response to the user's input from the
        database.

        This function queries the `responses` table in the connected SQLite
        database to find the best matching question based on the user's input.
        It compares the user's input to all stored questions using fuzzy string
        matching (via `fuzz.ratio`). If the best match has a score above 70,
        the corresponding answer is returned. Otherwise, `None` is returned.

        Args:
            user_input (str): The input provided by the user to be matched
            against stored questions.

        Returns:
            str or None: The answer corresponding to the best matching question
                         if the score is greater than 70, or `None` if no
                         suitable match is found.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT question, answer FROM responses")
        results = cursor.fetchall()

        best_match = None
        best_score = 0
        for question, answer in results:
            score = fuzz.ratio(user_input, question)
            if score > best_score:
                best_match = (question, answer)
                best_score = score
        if best_match and best_score > 70:
            return best_match[1]
        return None

    def listen(self, language="vi-VN"):
        """
        Listens for audio input from the microphone and converts it to text.

        This function continuously listens for audio input from the microphone
        using the `speech_recognition` library. Once audio is detected, it
        attempts to convert the audio to text using Google's speech recognition
        service. If the input is successfully recognized, it returns the text
        in lowercase. The function handles various exceptions such as
        unrecognized speech, timeouts, and service errors.

        Args:
            language (str): The language code (e.g., 'en' for English, 'vi' for
                            Vietnamese) to be used for speech recognition.

        Returns:
            str: The recognized speech as text in lowercase. If no valid speech
                 is recognized, the function will continue listening until input
                 is successfully captured.
        """
        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source)
            while True:
                try:
                    print("Listening...")
                    audio = self.recognizer.listen(
                        source,
                        timeout=20,
                        phrase_time_limit=15
                    )
                    text = self.recognizer.recognize_google(
                        audio,
                        language=language
                    )
                    print(f"You speak: {text}")
                    return text.lower()
                except sr.UnknownValueError:
                    print("Didn't catch that.")
                except sr.WaitTimeoutError:
                    print("Timeout reached without input.")
                except sr.RequestError as err:
                    time.sleep(5 * 60)
                    print(f"Speech recognition service error: {err}")

    def youtube_mode(self, user_input):
        """
        Listens for audio input from the microphone and converts it to text.

        This function continuously listens for audio input from the microphone
        using the `speech_recognition` library. Once audio is detected, it
        attempts to convert the audio to text using Google's speech recognition
        service. If the input is successfully recognized, it returns the text
        in lowercase. The function handles various exceptions such as
        unrecognized speech, timeouts, and service errors.

        Args:
            language (str): The language code (e.g., 'en' for English, 'vi' for
                            Vietnamese) to be used for speech recognition.

        Returns:
            str: The recognized speech as text in lowercase. If no valid speech
                 is recognized, the function will continue listening until input
                 is successfully captured.
        """
        running = [True]
        enter_match = self.get_best_match(user_input, self.enter_youtube_options)
        if enter_match:
            self.speak(f"{enter_match} {self.voice_dict['youtube_mode']}")
            while True:
                running[0] = True
                voice_input = self.listen()
                if voice_input:
                    if self.change_volume_by_voice(voice_input):
                        continue
                    exit_match = self.get_best_match(
                        voice_input,
                        self.exit_youtube_options
                    )
                    if exit_match:
                        self.speak(exit_match)
                        break
                    if self.voice_dict["hello"] in voice_input:
                        self.speak(self.voice_dict["youtube_hello"])
                        continue
                    video_url = self.search_mp4(voice_input)
                    if video_url:
                        self.speak(f"{self.voice_dict['find_video']} {voice_input},"
                                   f" {self.voice_dict['wait_30s']}")
                        thread = self.listen_voice_in_thread(
                            running, self.stop_video_options
                        )
                        self.play_video(video_url)
                        running[0] = False
                        self.speak(self.voice_dict["end_video"])
                        thread.join()
                        self.speak(self.voice_dict["more_video"])
                    else:
                        self.speak(f"{self.voice_dict['no_video_found']} "
                                   f"{voice_input}")

    def main(self):
        """
        The main entry point for the chatbot, handling user interaction and
        different modes.

        This function checks for an internet connection, loads necessary options,
        and begins listening for user input. It handles various commands such as
        starting YouTube mode, playing a story, adjusting the volume, or responding
        to other queries. If no valid options are found in the configuration files
        (JSON), the function will notify the user. The chatbot responds in
        Vietnamese and handles multiple scenarios based on the user's input.

        Returns:
            None: The function runs in an infinite loop, continuously processing
                  user input.
        """
        if not self.check_internet():
            self.no_internet_speak()
        else:
            if (not self.story_options or not self.enter_youtube_options
                    or not self.exit_youtube_options
                    or not self.stop_video_options
                    or not self.voice_dict):
                self.speak(self.voice_dict["unknown_options"])
            else:
                self.speak(self.voice_dict["hello"])
                while True:
                    user_input = self.listen()
                    if user_input:
                        if self.change_volume_by_voice(user_input):
                            continue
                        match = self.get_best_match(user_input, self.story_options)
                        if match:
                            self.speak(f"{self.voice_dict['waiting']} {match}")
                            match_res = self.get_response(match)
                            if match_res:
                                self.speak(match_res)
                                continue
                        self.youtube_mode(user_input)
                        response = self.get_response(user_input)
                        if response:
                            self.speak(response)
                        else:
                            self.speak(self.voice_dict["unknown_answer"])


if __name__ == "__main__":
    bot = ChatBot()
    bot.main()
