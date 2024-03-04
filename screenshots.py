'''
Screenshots - Take previw screenshots using vapoursynth

Upload to catbox, imgur or slowpics (or keep local)

Requirements:
    - Python 3.10+ (tested on 3.11.8)
    - vapoursynth (tested on R65)

    - python packages: requests, rich, vs-tools, requests-toolbelt
    - vapoursynth plugins: L-SMASH-Works, Subtext
'''

############################################################################################################################################################
############################################################################################################################################################
############################################################################################################################################################

# Files dict list
# Example: r'file_to_compare.mkv'
FILE = r'C:\Users\Sylvain\Documents\Travail\Dev\toolbox\Boku no Kokoro no Yabai Yatsu S2 - 09 - 1080p WEB H.264 -WeebGakuin (B-Global).mkv'

FRAMES_COUNT = 3
# Custom frames to use (if any)
# Example: [0, 40, 500]
CUSTOM_FRAMES = []

FRAME_INFOS = False # Display frame informations
RESCALING_RESOLUTION = None # Set rescale resolution

UPLOAD_PROVIDER = None # Can be catbox, imgur or slowpics (or None if no upload it online)
UPLOAD_PROXY = None # Proxy to use when upload
UPLOAD_NAME = None # Upload collection name
UPLOAD_DESCRIPTION = None # Upload collection description

CATBOX_TOKEN = None # To save file and collection to a catbox account
SLOWPICS_PUBLIC = False # Set slowpics post to public
SLOWPICS_LIMITED = False # If post contain images not suitable for minors (nudity, gore, etc.)
SLOWPICS_EXPIRATION = 1 # Slowpics post expiration time in days (0 = disable)

KEEP_IMAGES = False # Keep the original after upload
KEEP_IMAGES_PATH = None # Path to save images

VS_RAM_LIMIT = 3000 # Ram allowed to vapoursynth (in MB)

############################################################################################################################################################
############################################################################################################################################################
############################################################################################################################################################

from collections import namedtuple
import hashlib
import math
from pathlib import Path
import random
import re
import shutil
from typing import Any, Optional
import uuid
from requests import Session
import requests
from requests_toolbelt import MultipartEncoder
from vapoursynth import core, VideoNode, RGB24
from rich.progress import Progress
from rich.console import Console
import vstools


core.max_cache_size = VS_RAM_LIMIT
TEMP_DIR = Path(__file__).parent / '.temp'


def get_clip(filepath: str) -> Optional[VideoNode]:
    file = Path(filepath).absolute()

    if not file.exists():
        return None

    try:
        clip = core.lsmas.LWLibavSource(str(file))
    except:
        return None

    clip = clip.std.PlaneStats()
    clip = clip.misc.SCDetect()

    return clip


def get_frame_stats(clip: VideoNode, frame_index: int) -> dict[str, Any]:
    if frame_index < 0 or frame_index + 1 > clip.num_frames:
        return None

    with clip.get_frame(frame_index) as frame:
        frame_infos = {
            'index': frame_index,
            '_raw': namedtuple('frame_props', ['format', 'width', 'height'])(
                frame.format, frame.width, frame.height
            )
        }

        avg = frame.props.get('PlaneStatsAverage')

        if 0.062746 <= avg <= 0.380000:
            frame_infos['type'] = 'dark'
        elif 0.450000 <= avg <= 0.800000:
            frame_infos['type'] = 'light'
        else:
            frame_infos['type'] = 'random'

        for key in frame.props:
            data = frame.props[key]
            
            if key.startswith('_'):
                key = key[1:]
            
            if isinstance(data, (bytes, bytearray)):
                try:
                    data = data.decode('utf-8')
                except:
                    pass
            
            frame_infos[key] = data

    return frame_infos


def save_frame(filepath: str | Path, frame_stats: dict[str, Any], quality: Optional[int] = None) -> Path:
    clip = core.lsmas.LWLibavSource(str(filepath))

    filename = Path(filepath).name
    output_dir = (TEMP_DIR if not KEEP_IMAGES or not KEEP_IMAGES_PATH else Path(KEEP_IMAGES_PATH)).absolute()
    output = output_dir / f'{hashlib.md5(filename.encode("utf-8")).digest().hex()}-{frame_stats.get("index")}.png'

    if not output.parent.exists():
        output.parent.mkdir(parents=True)

    if quality is None:
        quality = clip.height

    matrix = clip.get_frame(0).props._Matrix
    if matrix == 2:
        matrix = 1

    clip = clip.resize.Spline36(
        vstools.get_w(quality or clip.height, clip), quality or clip.height,
        format=RGB24, matrix_in=matrix, dither_type='error_diffusion'
    )

    if FRAME_INFOS:
        font_size = 25 if quality == 720 else math.ceil(25 / (720 / quality))
        font_style = f'Consolas,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HCB000000,-1,0,0,0,100,100,0,0,3,0,0.1,7,0,0,0,1'

        text = 'Filename: %s\nFrame: %s\nPicture type: %s\nOriginal resolution: %s\nColor matrix: %s\nColor range: %s' % (
            filename,
            str(frame_stats.get('index')),
            frame_stats.get('PictType'),
            f'{clip.width}x{clip.height}',
            vstools.Matrix.from_video(frame_stats.get('_raw')).name,
            vstools.ColorRange.from_video(frame_stats.get('_raw')).name
        )

        clip = clip.sub.Subtitle(
            text=text,
            start=frame_stats.get('index'),
            end=frame_stats.get('index') + 1,
            style=font_style
        )

    clip.imwri.Write(
        'PNG',
        str(output),
        overwrite=True,
    ).get_frame(frame_stats.get('index'))

    return output


def upload_catbox(screenshots: list[Path]) -> str:
    with Progress() as progress:
        images = []
        task = progress.add_task('[cyan]:inbox_tray: Uploading images to catbox', total=len(screenshots) + 1)

        for screenshot in screenshots:
            with screenshot.open('rb') as f:
                files = MultipartEncoder({
                    'fileToUpload': (screenshot.name, f, 'image/png'),
                    'userhash': CATBOX_TOKEN or '',
                    'reqtype': 'fileupload'
                })

                req = requests.post('https://catbox.moe/user/api.php', data=files.to_string(), headers={
                    'Content-Type': files.content_type,
                    'Content-Length': str(files.len),
                }, proxies={'all': UPLOAD_PROXY})
                req.raise_for_status()

                images.append(req.text.split('/').pop())
                progress.update(task, advance=1)
                

        files = MultipartEncoder({
            'files': ' '.join(images),
            'reqtype': 'createalbum',
            'title': UPLOAD_NAME,
            'desc': UPLOAD_DESCRIPTION,
            **({'userhash': CATBOX_TOKEN} if CATBOX_TOKEN else {})
        })

        req = requests.post('https://catbox.moe/user/api.php', data=files.to_string(), headers={
            'Content-Type': files.content_type,
            'Content-Length': str(files.len),
        }, proxies={'all': UPLOAD_PROXY})
        req.raise_for_status()

        progress.update(task, advance=1)
    
    return req.text


def upload_imgur(screenshots: list[Path]) -> str:
    with Progress() as progress:
        images = []
        task = progress.add_task('[cyan]:inbox_tray: Uploading images to imgur', total=len(screenshots) + 1)

        req = requests.get('https://s.imgur.com/desktop-assets/js/main.534665f6f523856a0e6e.js')
        req.raise_for_status()

        match = re.search(r'apiClientId:"(?P<clientId>[a-zA-Z0-9]+)"', req.text)
        if not match:
            raise Exception('Unable to find clientId')
        
        clientId = match.groupdict().get('clientId')

        for screenshot in screenshots:
            with screenshot.open('rb') as f:
                files = MultipartEncoder({
                    'image': (screenshot.name, f, 'image/png'),
                    'type': 'image'
                })

                req = requests.post('https://api.imgur.com/3/image', data=files.to_string(), headers={
                    'Content-Type': files.content_type,
                    'Content-Length': str(files.len),
                    'Authorization': f'Client-ID {clientId}'
                }, proxies={'all': UPLOAD_PROXY})
                req.raise_for_status()

                images.append(req.json().get('data').get('deletehash'))
                progress.update(task, advance=1)

        fields = {'title': UPLOAD_NAME, 'description': UPLOAD_DESCRIPTION}

        for index, image in enumerate(images):
            fields[f'deletehashes[{index}]'] = image

        files = MultipartEncoder(fields)

        req = requests.post('https://api.imgur.com/3/album', data=files.to_string(), headers={
            'Content-Type': files.content_type,
            'Content-Length': str(files.len),
            'Authorization': f'Client-ID {clientId}'
        }, proxies={'all': UPLOAD_PROXY})
        req.raise_for_status()

        progress.update(task, advance=1)
    
    return f'https://imgur.com/a/{req.json().get("data").get("id")}'


def upload_slowpics(screenshots: list[Path]) -> str:
    with Session() as session:
        with Progress() as progress:
            task = progress.add_task('[cyan]:inbox_tray: Uploading images', total=len(screenshots) + 1)

            if UPLOAD_PROXY:
                session.proxies.update({'all': UPLOAD_PROXY})

            fields = {
                'collectionName': UPLOAD_NAME,
                'public': 'true' if SLOWPICS_PUBLIC else 'false',
                'optimize-images': 'true',
                'hentai': 'true' if SLOWPICS_LIMITED else 'false',
                'browserId': str(uuid.uuid4()),
            }

            if SLOWPICS_EXPIRATION is not None:
                fields['removeAfter'] = str(SLOWPICS_EXPIRATION)

            for index, screenshot in enumerate(screenshots):
                fields[f'imageNames[{index}]'] = screenshot.name

            session.get('https://slow.pics/collection')
            files = MultipartEncoder(fields, str(uuid.uuid4()))

            session.headers.update({
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'en-US,en;q=0.9',
                'Access-Control-Allow-Origin': '*',
                'Origin': 'https://slow.pics/',
                'Referer': 'https://slow.pics/collection',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
            })

            req = session.post(
                'https://slow.pics/upload/collection',
                data=files,
                headers={
                    'Content-Type': files.content_type,
                    'Content-Length': str(files.len),
                    'X-XSRF-TOKEN': session.cookies.get_dict().get('XSRF-TOKEN')
                }
            )
            
            req.raise_for_status()
            progress.update(task, advance=1)
            data = req.json()
            
            for index, image_id in enumerate(data.get('images')[0]):
                image: Path = screenshots[index]

                with image.open('rb') as f:
                    fields = {
                        'collectionUuid': data.get('collectionUuid'),
                        'imageUuid': image_id,
                        'file': (image.name, f, 'image/png'),
                        'browserId': fields.get('browserId'),
                    }

                    files = MultipartEncoder(fields, str(uuid.uuid4()))

                    req = session.post(
                        'https://slow.pics/upload/image',
                        data=files,
                        headers={
                            'Content-Type': files.content_type,
                            'Content-Length': str(files.len),
                            'X-XSRF-TOKEN': session.cookies.get_dict().get('XSRF-TOKEN')
                        }
                    )

                req.raise_for_status()
                progress.update(task, advance=1)

    return f'https://slow.pics/c/{data.get("key")}'


def main():
    console = Console()

    if not KEEP_IMAGES and not UPLOAD_PROVIDER:
        console.print('[red]KEEP_IMAGES is not set to false but UPLOAD_PROVIDER is set to false too, images are not saved anywere!')
        exit(1)

    if UPLOAD_PROVIDER and UPLOAD_PROVIDER.lower() not in ['catbox', 'imgur', 'slowpics']:
        console.print('[red]UPLOAD_PROVIDER seem to be invalid, must be one of slowpics, catbox or imgur')
        exit(1)

    if KEEP_IMAGES and not KEEP_IMAGES_PATH:
        console.print('[red]KEEP_IMAGES set to true but no KEEP_IMAGES_PATH set!')
        exit(1)

    if FRAMES_COUNT < 1 and len(CUSTOM_FRAMES) < 1:
        console.print('[red]No frame to capture!')
        exit(1)
    
    clip = get_clip(FILE)

    console.clear()
    console.rule(style='cyan')

    if not clip:
        console.print('[red]Invalid file provided!')
        exit(1)

    if FRAMES_COUNT + len(CUSTOM_FRAMES) > clip.num_frames:
        console.print('[red]Too many frames requested!')
        exit(1)

    if any([index > clip.num_frames for index in CUSTOM_FRAMES]):
        console.print('[red]Invalid custom frames provided!')
        exit(1)
    
    frames_index = random.sample([index for index in range(clip.num_frames) if index not in CUSTOM_FRAMES], FRAMES_COUNT)
    files = []

    with Progress() as progress:
        task = progress.add_task('[cyan]:film_frames: Saving frames', total=len(CUSTOM_FRAMES) + FRAMES_COUNT)
        
        for frame_index in frames_index + CUSTOM_FRAMES:
            files.append(save_frame(FILE, get_frame_stats(clip, frame_index), RESCALING_RESOLUTION))
            progress.update(task, advance=1)

    console.rule(style='cyan')

    if UPLOAD_PROVIDER:
        url = {
            'catbox': upload_catbox,
            'imgur': upload_imgur,
            'slowpics': upload_slowpics
        }[UPLOAD_PROVIDER](files)

        console.print(f'[cyan]:link: URL: [url={url}]{url}[/url]')

        console.rule(style='cyan')

    with Progress() as progress:
        progress.add_task('[cyan]:broom: Cleanning temp files')

        lwi = Path(f'{FILE}.lwi')

        if lwi.exists():
            lwi.unlink()
            
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
        
        progress.update(task, total=1, advance=1)

    console.rule(style='cyan')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass