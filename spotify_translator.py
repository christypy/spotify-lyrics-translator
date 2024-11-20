import tkinter as tk
from tkinter import ttk
from deep_translator import GoogleTranslator
from syrics.api import Spotify
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pykakasi
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Spotify API credentials
SPOTIPY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')

# Initialize Spotify API
sp_lyrics = Spotify("AQDZjVPYmGj0nyTBZ9qLRWez7mYxOABd-b7V4D3r5bxCsgf_F1QaT_c1pqjyf5Mv3EzuclD0OGRxj6fj0GG9Il51-OmOe5hAXKdJXE6YlDG-vi5ps745fBCMIk1lA7_Q54KT7O8J8-YEVvK7TjfmE9S7KzadQsORH9OcD1g7AFpApEuBmokBCVyPnN7d9jYOYNtc3xfkg8QrGaMz1N2MiU0eMIJk")
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                                              client_secret=SPOTIPY_CLIENT_SECRET,
                                              redirect_uri=SPOTIPY_REDIRECT_URI,
                                              scope="user-modify-playback-state user-read-playback-state"))

# Initialize kakasi for romaji conversion
kks = pykakasi.Kakasi()
converter = kks.convert

# Cache to store the translated lyrics
CACHE_FILE = 'lyrics_cache.pkl'
MAX_CACHE_SIZE = 1000

current_song_id = None
translation_complete = False
translated_lyrics_cache = None
language = ""

# Load cache from file if it exists
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        lyrics_cache = pickle.load(f)
else:
    lyrics_cache = {}

# Function to save cache to file
def save_cache():
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(lyrics_cache, f)

# Function to get the current song and playback position
def get_current_playback_position():
    try:
        current_song = sp_lyrics.get_current_song()
        position_ms = current_song['progress_ms']
        return current_song, position_ms
    except Exception as e:
        print(f"Error fetching current song playback position: {e}")
        return None, 0

# Function to update the Treeview and the current time label
def update_display():
    global current_song_id
    current_song, current_position = get_current_playback_position()
    if current_song:
        song_id = current_song['item']['id']
        if song_id != current_song_id:
            current_song_id = song_id
            update_lyrics()

        current_time_label.config(text=f"Current Time: {ms_to_min_sec(current_position)}")
        last_index = None
        for item in tree.get_children():
            item_data = tree.item(item)
            start_time = int(item_data['values'][0].split(":")[0]) * 60000 + int(item_data['values'][0].split(":")[1]) * 1000
            if start_time <= current_position:
                last_index = item
            else:
                break
        if last_index:
            tree.selection_set(last_index)
            tree.see(last_index)

    root.after(500, update_display)  # Reduced the update frequency

# Function to convert milliseconds to minutes:seconds format
def ms_to_min_sec(ms):
    ms = int(ms)
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    return f"{minutes}:{seconds:02}"

# Function to translate a single lyric line
def translate_line(translator, line):
    original_text = line['words']
    try:
        translated_text = translator.translate(original_text)
    except Exception as e:
        print(f"Error translating '{original_text}': {e}")
        translated_text = original_text
    return {'startTimeMs': line['startTimeMs'], 'words': original_text, 'translated': translated_text}

# Function to translate lyrics using multithreading
def translate_words(lyrics, song_name, song_id, callback):
    global translation_complete, translated_lyrics_cache
    translator = GoogleTranslator(source='auto', target='zh-TW')
    translated_song_name = translator.translate(song_name)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(translate_line, translator, line) for line in lyrics]
        translated_lyrics = [future.result() for future in as_completed(futures)]
    lyrics_cache[song_id] = translated_lyrics  # Store the result in the cache

    # Ensure the cache size does not exceed the limit
    if len(lyrics_cache) > MAX_CACHE_SIZE:
        lyrics_cache.pop(next(iter(lyrics_cache)))

    save_cache()
    callback(translated_lyrics)
    translation_complete = True

# Function to update the lyrics in the Treeview
def update_lyrics():
    global current_song_id, translation_complete

    current_song = sp_lyrics.get_current_song()
    song_id = current_song['item']['id']
    song_name = current_song['item']['name']
    lyrics = sp_lyrics.get_lyrics(song_id)
    lyrics_data = lyrics['lyrics']['lines'] if lyrics and 'lyrics' in lyrics and 'lines' in lyrics['lyrics'] else None

    root.title(f"{song_name}")

    tree.delete(*tree.get_children())

    if lyrics_data:
        # Detect the language of the first line of lyrics
        detected_lang = lyrics['lyrics']['language']
        global language
        language = detected_lang
        tree.heading("Original Lyrics", text=f"Original Lyrics ({detected_lang})")

        for index, lyric in enumerate(lyrics_data):
            original_text = lyric['words']
            if language == "ja":
                romaji = get_romaji(original_text)
                display_text = f"{romaji}\n{original_text}" if romaji else original_text
            else:
                display_text = original_text
            tree.insert("", "end", values=(ms_to_min_sec(lyric['startTimeMs']), display_text, ""))

        translation_complete = False
        if song_id in lyrics_cache:
            update_translations(lyrics_cache[song_id])
        else:
            threading.Thread(target=translate_words, args=(lyrics_data, song_name, song_id, update_translations)).start()
    else:
        tree.insert("", "end", values=("0:00", "(No lyrics)", ""))
    adjust_column_widths()

# Function to update the Treeview with translated lyrics
def update_translations(translated_lyrics):
    for item in tree.get_children():
        item_data = tree.item(item)
        start_time = item_data['values'][0]
        original_lyrics = item_data['values'][1]
        for lyric in translated_lyrics:
            if ms_to_min_sec(lyric['startTimeMs']) == start_time and lyric['words'] == original_lyrics.split('\n')[-1]:
                tree.set(item, column="Translated Lyrics", value=lyric['translated'])
                break
    if tree.get_children():
        first_item = tree.get_children()[0]
        tree.set(first_item, column="Translated Lyrics", value=translated_lyrics[0]['translated'])
    adjust_column_widths()

# Function to find the longest line length in original and translated lyrics
def find_longest_line_lengths():
    max_original_length = 0
    max_translated_length = 0
    line_count = 0

    for item in tree.get_children():
        line_count += 1
        original_length = len(tree.item(item)['values'][1])
        translated_length = len(tree.item(item)['values'][2])
        if original_length > max_original_length:
            max_original_length = original_length
        if translated_length > max_translated_length:
            max_translated_length = translated_length

    return max_original_length, max_translated_length, line_count

# Function to adjust the column widths based on the content
def adjust_column_widths():
    min_time_width = 60  # Minimum width for the "Time" column
    max_original_length, max_translated_length, line_count = find_longest_line_lengths()

    root.update_idletasks()
    width = tree.winfo_reqwidth()

    orig_length=max_original_length*15
    trans_length = max_translated_length * 15

    if language=="ja":
        orig_length=max_original_length*23
    if language=="ru":
        orig_length=max_original_length*18
        trans_length=max_translated_length*19

    width = min_time_width + orig_length + trans_length

    # Get the required height for the treeview
    tree_height = tree.winfo_reqheight()

    # Add the height of the current time label and some padding
    height = line_count * 50 + 100

    #print(f"Width: {width}, Height: {height}")
    #print(f"Max Original Length: {max_original_length}, Max Translated Length: {max_translated_length}")

    # Update the window size
    # get current width
    current_width = root.winfo_width()

    tree.column("Time", width=min_time_width, minwidth=min_time_width)
    tree.column("Original Lyrics", width=orig_length)
    tree.column("Translated Lyrics", width=trans_length)
    root.geometry(f"{current_width}x{height}")

def get_romaji(text):
    try:
        result = converter(text)
        return ''.join([item['hepburn'] for item in result])
    except:
        return ""

def previous_lyric():
    selection = tree.selection()
    if selection:
        current_item = selection[0]
        prev_item = tree.prev(current_item)
        if prev_item:
            tree.selection_set(prev_item)
            tree.see(prev_item)
            seek_to_lyric(prev_item)

def next_lyric():
    selection = tree.selection()
    if selection:
        current_item = selection[0]
        next_item = tree.next(current_item)
        if next_item:
            tree.selection_set(next_item)
            tree.see(next_item)
            seek_to_lyric(next_item)

def repeat_current_lyric():
    selection = tree.selection()
    if selection:
        current_item = selection[0]
        seek_to_lyric(current_item)

def seek_to_lyric(item):
    item_data = tree.item(item)
    time_str = item_data['values'][0]
    minutes, seconds = map(int, time_str.split(':'))
    position_ms = (minutes * 60 + seconds) * 1000
    try:
        sp.seek_track(position_ms)
    except Exception as e:
        print(f"Error seeking to position: {e}")

# Create main application window
root = tk.Tk()
root.title("Spotify Lyrics Translator")
root.configure(bg='#282828')  # Spotify's dark theme background color

# Apply a theme to the Tkinter application
style = ttk.Style(root)
style.theme_use("default")

# Configure styles
style.configure("Control.TFrame", background='#282828')
style.configure("Control.TButton",
    padding=10,
    background='#1DB954',  # Spotify green
    foreground='white',
    font=('Helvetica', 10, 'bold')
)
style.map("Control.TButton",
    background=[('active', '#1ed760')],  # Lighter green on hover
    foreground=[('active', 'white')]
)

style.configure("Treeview",
    background='#121212',  # Darker background for contrast
    foreground='#FFFFFF',  # White text
    fieldbackground='#121212',
    font=('Helvetica', 12),
    rowheight=50
)
style.configure("Treeview.Heading",
    background='#1DB954',  # Spotify green
    foreground='white',
    font=('Helvetica', 12, 'bold'),
    padding=5
)
style.map("Treeview",
    background=[('selected', '#1DB954')],  # Spotify green for selection
    foreground=[('selected', 'white')]
)

# Create control buttons frame with padding and background
control_frame = ttk.Frame(root, style="Control.TFrame", padding="10 10 10 5")
control_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

# Style the buttons
prev_button = ttk.Button(control_frame, text="◀ Previous", style="Control.TButton", command=previous_lyric)
prev_button.pack(side=tk.LEFT, padx=5)

next_button = ttk.Button(control_frame, text="Next ▶", style="Control.TButton", command=next_lyric)
next_button.pack(side=tk.LEFT, padx=5)

repeat_button = ttk.Button(control_frame, text="↻ Repeat", style="Control.TButton", command=repeat_current_lyric)
repeat_button.pack(side=tk.LEFT, padx=5)

# Current time label with modern styling
current_time_label = tk.Label(
    root,
    text="Current Time: 00:00",
    font=('Helvetica', 12, 'bold'),
    bg='#282828',  # Match root background
    fg='#1DB954',  # Spotify green
    padx=15,
    pady=10
)
current_time_label.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(5, 10))

# Create a frame to hold the Treeview and Scrollbar with padding
frame = ttk.Frame(root, style="Control.TFrame", padding="10 5 10 10")
frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

# Configure the Treeview
tree = ttk.Treeview(frame, columns=("Time", "Original Lyrics", "Translated Lyrics"), show="headings", style="Treeview")
tree.heading("Time", text="Time", anchor='w')
tree.heading("Original Lyrics", text="Original Lyrics", anchor='w')
tree.heading("Translated Lyrics", text="Translated Lyrics", anchor='w')

# Configure column widths
tree.column("Time", width=100, minwidth=100, anchor='w')
tree.column("Original Lyrics", width=300, minwidth=200, anchor='w')
tree.column("Translated Lyrics", width=300, minwidth=200, anchor='w')

# Style the scrollbar
style.configure("Vertical.TScrollbar",
    background='#282828',
    troughcolor='#121212',
    width=16,
    arrowsize=16
)

# Create and configure the Scrollbar
scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Vertical.TScrollbar")
tree.configure(yscrollcommand=scrollbar.set)

# Pack the Treeview and Scrollbar
tree.pack(side='left', fill=tk.BOTH, expand=True)
scrollbar.pack(side='right', fill='y')

# Set minimum window size
root.minsize(800, 600)

# Center the window on screen
window_width = 900
window_height = 700
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
center_x = int(screen_width/2 - window_width/2)
center_y = int(screen_height/2 - window_height/2)
root.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')

# Start the update in a non-blocking manner
root.after(500, update_display)  # Initial call to start the loop with reduced frequency

# Start the application
root.mainloop()