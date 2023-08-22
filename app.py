import streamlit as st
from yt_dlp import YoutubeDL
import os
import re
from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel
from clarifai_grpc.grpc.api import resources_pb2, service_pb2, service_pb2_grpc
from clarifai_grpc.grpc.api.status import status_code_pb2

format_prompt = '''[INST] Below is the transcript of a video. Please correct the capitalization and 
punctuation, including making separate paragraphs, without changing any of the text. If a word 
is misspelled, correct the word, and if a word does not exist take your best guess as to the 
correct word. Only return the corrected text without commentary. [/INST]'''
video_prompt = '[INST] Write a YouTube video title and video description for the following video script. [/INST]'

# Model configurations
models = {
    'Llama2-7b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'Llama2-7b-chat',
        'MODEL_VERSION_ID': 'e52af5d6bc22445aa7a6761f327f7129'
    },
    'Llama2-13b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'llama2-13b-chat',
        'MODEL_VERSION_ID': '79a1af31aa8249a99602fc05687e8f40'
    },
    'Llama2-70b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'llama2-70b-chat',
        'MODEL_VERSION_ID': '6c27e86364ba461d98de95cddc559cb3'
    },
    'GPT-3': {
        'USER_ID': 'openai',
        'APP_ID': 'chat-completion',
        'MODEL_ID': 'GPT-3_5-turbo',
        'MODEL_VERSION_ID': '8ea3880d08a74dc0b39500b99dfaa376'
    },
    'GPT-4': {
        'USER_ID': 'openai',
        'APP_ID': 'chat-completion',
        'MODEL_ID': 'GPT-4',
        'MODEL_VERSION_ID': 'ad16eda6ac054796bf9f348ab6733c72'
    }
}

def filter_subtitles(subtitle_str):
    lines = subtitle_str.strip().split("\n")
    
    past_header = False
    content_lines = []
    capture_next = False

    for line in lines:
        line = line.strip()

        if "-->" in line:
            past_header = True
            capture_next = True
            continue
        
        if not past_header:
            continue
        
        # If line has no tags and we are set to capture, add to content
        if capture_next and line and "<" not in line and ">" not in line:
            if not content_lines or (content_lines and content_lines[-1] != line):
                content_lines.append(line)
            capture_next = False

    return "\n".join(content_lines)

def extract_video_id(url_or_id):
    """
    Extracts the YouTube video ID from a URL or returns the ID if it's already just an ID.
    """
    match = re.search(r"(?<=v=)[\w-]+", url_or_id)
    return match.group(0) if match else url_or_id

def download_subtitles(video_id):
    """
    Downloads subtitles for a given video ID and returns the content.
    """
    temp_file_path = "/tmp/temp_subtitle_file"
    full_temp_file_path = temp_file_path + ".en.vtt"
    ydl_opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "sleep_interval_subtitles": 1,
        "outtmpl": temp_file_path,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_id])
    
    with open(full_temp_file_path, "r", encoding="utf-8") as file:
        content = file.read()
    
    # Clean up the temporary file
    os.remove(full_temp_file_path)

    return filter_subtitles(content).replace('\n', ' ').replace('\r', '')

def format_with_clarifai_api(raw_text, prompt):

    full_prompt = prompt + '\n' + raw_text + '\n'
    PAT = os.environ.get('CLARIFAI_PAT') 

    if not PAT:  # If PAT is not set via environment variable
        try:
            PAT = st.secrets['CLARIFAI_PAT']
        except KeyError:
            st.error("Failed to retrieve the Clarifai Personal Access Token!")
            PAT = None

    channel = ClarifaiChannel.get_grpc_channel()
    stub = service_pb2_grpc.V2Stub(channel)

    metadata = (('authorization', 'Key ' + PAT),)

    userDataObject = resources_pb2.UserAppIDSet(
        user_id=selected_model['USER_ID'], 
        app_id=selected_model['APP_ID']
    )

    post_model_outputs_response = stub.PostModelOutputs(
        service_pb2.PostModelOutputsRequest(
            user_app_id=userDataObject,
            model_id=selected_model['MODEL_ID'],
            version_id=selected_model['MODEL_VERSION_ID'],
            inputs=[
                resources_pb2.Input(
                    data=resources_pb2.Data(
                        text=resources_pb2.Text(
                            raw=full_prompt  # Send the raw text here
                        )
                    )
                )
            ]
        ),
        metadata=metadata
    )

    if post_model_outputs_response.status.code != status_code_pb2.SUCCESS:
        st.error(f"Error from Clarifai API: {post_model_outputs_response.status.description}")
        return None

    output = post_model_outputs_response.outputs[0]
    # Check if output is not None and then strip it
    return output.data.text.raw.strip() if output.data.text.raw else None

def extract_string(s):
    # Search for content inside triple quotes
    match = re.search(r'\"\"\"(.*?)\"\"\"', s, re.DOTALL)
    return match.group(1) if match else None

st.title("YouTube Script, Title, and Description Generator")

# Callout text
st.markdown('''
**This app is designed to automate some of the steps in creating a YouTube video.**
When you upload a video, YouTube will automatically create English subtitled word-by-word. Sometimes it does a great job, sometimes a poor one, but it's usually a great starting place for creating proper subtitles for your video. Ideally this should work with videos about ~5 minutes long at most, since longer videos will have longer scripts that may exceed the context of the LLM used.

To use this app as intended, do the following:

- Upload an English language YouTube video and wait for YouTube to create the automatically generated subtitles.
- Once YouTube has generated the subtitles, use this app. Enter either the full URL or just the video code (for example, either `https://www.youtube.com/watch?v=a4sHHnlasPQ` or `a4sHHnlasPQ`)
- The app will pull the auto-generated subtitles. Choose a model to try. The choices are `Llama-2-7b`, `Llama-2-13b`, and `Llama-2-13b`, as well as OpenAI's `GPT-3` and `GPT-4`.
- The app will create a formatted version of the script. You may need to copy it to another document and review it for errors and corrections, as the speech-to-text from YouTube and the punctuating from the LLM may have left a few problems.
- Click the "Generate title and description" to have the model propose a title and description for the video.

This way, the steps of formatting the script for subtitles, the video title, and the video description, can all be automated!
''')

# Input for YouTube URL or video ID
url_or_id = st.text_input("Enter YouTube URL or Video ID:")

# Add the model selection dropdown
selected_model_name = st.selectbox("Select Model:", list(models.keys()))
selected_model = models[selected_model_name]

subtitles = None  # Initialize subtitles to None

# If URL or ID is provided, process it
if url_or_id: 
    video_id = extract_video_id(url_or_id)
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"  # Construct the full YouTube URL
    # Display the YouTube video embedded on the page
    st.video(youtube_url)

    try:
        subtitles = download_subtitles(video_id)
        st.text_area("Subtitles:", value=subtitles, height=400)
    except Exception as e:
        st.error(f"An error occurred: {e}")

if 'formatted_text' not in st.session_state:
    st.session_state.formatted_text = None

if subtitles:  # If raw subtitles were fetched and displayed
    if st.button("Punctuate Script"):
        st.session_state.formatted_text = format_with_clarifai_api(subtitles, format_prompt)

    # Only show the formatted text if it exists
    if st.session_state.formatted_text:
        st.text_area("Formatted Subtitles:", value=st.session_state.formatted_text, height=400)
        
        # Check for the st.session_state.formatted_text before showing the "Generate title and description" button
        if st.button("Generate title and description"):
            # Generate title and description
            video_description = format_with_clarifai_api(st.session_state.formatted_text, video_prompt)
            st.text_area("Generated Title and Description:", value=video_description, height=400)

st.write("""
**Note**: Please ensure the video has available subtitles. 
Also, be aware of YouTube's terms of service when downloading and using content.
""")
