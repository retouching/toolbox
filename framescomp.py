'''
FramesComp - Video frames comparison tool

Compare from different sources to see what source is better to use.
Slowpics upload is supported.

Sources:
 - https://gist.github.com/Vodes/300997ac1473ac2b9d08d62c169a26de
 - https://github.com/McBaws/comp

Requirements:
    - Python 3.10+
    - vapoursynth (tested on R65)

    - python packages: requests, rich, vs-tools, requests-toolbelt
    - vapoursynth plugins: L-SMASH-Works, Subtext
'''

############################################################################################################################################################
############################################################################################################################################################
############################################################################################################################################################

# Files dict list
# Example: [{'file': 'file_to_compare.mkv', 'fps': [24, 1], 'sync': -5}]
# - fps and sync are not required
FILES = []

DARK_FRAMES = 3 # Dark scenes to capture
LIGHT_FRAMES = 3 # Light scenes to capture
RANDOM_FRAMES = 3 # Random (non dark/light) scenes to capture
# Custom frames to use (if any)
# Example: [{'file_index': 0, 'frame_index': 20}]
# - All fields are required
CUSTOM_FRAMES = []
FRAMES_TYPE = None # Can be I, P, B or None to take all (or false to disable frames type filtering) (https://en.wikipedia.org/wiki/Video_compression_picture_types)

UPSCALING = True # Upscale the captured scenes to the maximum resolution of videos
UPSCALING_RESOLUTION = None # Set upscale resolution or None to set to the upper available

SLOWPICS_ENABLED = True # Upload the captured scenes to slowpics
SLOWPICS_PROXY = None # Proxy to use when upload to slowpics
SLOWPICS_PUBLIC = False # Set slowpics post to public
SLOWPICS_LIMITED = False # If post contain images not suitable for minors (nudity, gore, etc.)
SLOWPICS_EXPIRATION = 1 # Slowpics post expiration time in days (0 = disable)
SLOWPICS_COLLECTION = None # Slowpics collection name

KEEP_IMAGES = False # Keep the original after upload
KEEP_IMAGES_PATH = None # Path to save images

VS_RAM_LIMIT = 300 # Ram allowed to vapoursynth (in MB)

############################################################################################################################################################
############################################################################################################################################################
############################################################################################################################################################

from collections import namedtuple
from fractions import Fraction
import hashlib
import math
from pathlib import Path
import random
import shutil
import sys
from typing import Any, Optional
import uuid
from requests import Session
from requests_toolbelt import MultipartEncoder
from vapoursynth import core, VideoNode, RGB24
from rich.progress import Progress
from rich.console import Console
import vstools


core.max_cache_size = VS_RAM_LIMIT
TEMP_DIR = Path(__file__).parent / '.temp'


def get_clip(filepath: str, fps: Optional[Fraction]) -> Optional[VideoNode]:
    file = Path(filepath).absolute()

    if not file.exists():
        return None

    try:
        clip = core.lsmas.LWLibavSource(str(file))
    except:
        return None

    if fps:
        fps = Fraction(numerator=fps[0], denominator=fps[1])
        current_fps = Fraction(numerator=clip.fps_num, denominator=clip.fps_den)

        if (int(float(fps) * 1000) / 1000) != (int(float(current_fps) * 1000) / 1000):
            clip = vstools.change_fps(clip, fps)

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
    output_dir = (TEMP_DIR if not KEEP_IMAGES or KEEP_IMAGES_PATH else Path(KEEP_IMAGES_PATH)).absolute()
    output = output_dir / f'{hashlib.md5(filename.encode("utf-8")).digest().hex()}-{frame_stats.get("index")}.png'

    if not output.parent.exists():
        output.parent.mkdir(parents=True)

    if quality is None:
        quality = clip.height
    
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

    matrix = clip.get_frame(0).props._Matrix
    if matrix == 2:
        matrix = 1

    clip = clip.resize.Spline36(
        vstools.get_w(quality or clip.height, clip), quality or clip.height,
        format=RGB24, matrix_in=matrix, dither_type='error_diffusion'
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


def main():
    console = Console()
    files_to_process = []

    if KEEP_IMAGES and not KEEP_IMAGES_PATH:
        console.print('[red]KEEP_IMAGES set to true but no KEEP_IMAGES_PATH set!')
        exit(1)

    if DARK_FRAMES < 1 and LIGHT_FRAMES < 1 and RANDOM_FRAMES < 1 and len(CUSTOM_FRAMES) < 1:
        console.print('[red]No frame type to capture!')
        exit(1)

    for file_data in FILES:
        clip = get_clip(file_data.get('file'), file_data.get('fps'))
        if clip:
            files_to_process.append({
                **file_data,
                'clip': clip,
                'sync': file_data.get('sync') or 0
            })

    if len(files_to_process) < 2:
        console.print('[red]You must have 2 files minimum to process')
        sys.exit(1)

    console.clear()
    console.rule(style='cyan')

    console.print('[cyan]:open_file_folder: Files selected:')
    for file in files_to_process:
        console.print(f'    :arrow_right: {Path(file.get("file")).name}', highlight=False)
    
    console.rule(style='cyan')

    frames = []
    max_frames = max(*[file.get('clip').num_frames for file in files_to_process])

    with Progress() as progress:
        task = progress.add_task('[cyan]:mag_right: Analysing files', total=max_frames)

        for i in range(max_frames):
            current_picture_type = FRAMES_TYPE
            current_frames = []
            push_frames = True

            for file in files_to_process:
                clip: VideoNode = file.get('clip')
                frame_index = i + file.get('sync')

                frame_infos = get_frame_stats(clip, frame_index)

                if not frame_infos:
                    push_frames = False
                    break

                if FRAMES_TYPE is not False and (current_picture_type and frame_infos.get('PictType') != current_picture_type):
                    push_frames = False
                    break

                current_picture_type = frame_infos.get('PictType')
                current_frames.append({'file': file.get('file'), 'index': frame_index, 'props': frame_infos})
            
            if push_frames:
                frames.append(current_frames)

            progress.update(task, advance=1)

    if UPSCALING_RESOLUTION:
        captue_resolution = UPSCALING_RESOLUTION
    elif UPSCALING:
        captue_resolution = max(*[file.get('clip').height for file in files_to_process])
    else:
        captue_resolution = None

    del files_to_process

    captures = {'custom': []}

    console.rule(style='cyan')
    
    for frames_type, frames_count in [('dark', DARK_FRAMES), ('light', LIGHT_FRAMES), ('random', RANDOM_FRAMES)]:
        if not frames_count or frames_count < 1:
            continue

        selected_frames = [grouped_frames for grouped_frames in frames if all([frame.get('props').get('type') == frames_type for frame in grouped_frames])]
        frames_count = frames_count if frames_count <= len(selected_frames) else len(selected_frames)

        if frames_count < 1:
            console.print(f'[dark_orange]No {frames_type} scene to capture, skipping')
            continue

        selected_frames = random.sample(selected_frames, frames_count)

        with Progress() as progress:
            task = progress.add_task(f'[cyan]:film_frames: Saving {frames_type} frames', total=frames_count * len(selected_frames[0]))
            captures_type = []

            for selected_frame in selected_frames:
                capture = []

                for frame in selected_frame:
                    frame['capture'] = save_frame(frame.get('file'), frame.get('props'), captue_resolution)
                    capture.append(frame)
                    progress.update(task, advance=1)
                
                captures_type.append(capture)

            captures[frames_type] = captures_type

    if len(CUSTOM_FRAMES) > 0:
        with Progress() as progress:
            task = progress.add_task(f'[cyan]:film_frames: Saving custom frames', total=len(CUSTOM_FRAMES) * len(FILES))

            for custom_frame in CUSTOM_FRAMES:
                file = FILES[custom_frame.get('file_index')]
                is_already_used = next(filter(
                    lambda captures_type: next(iter([captures for captures in captures_type if next(iter([
                        capture for capture in captures
                        if capture.get('file') == file.get('file') and capture.get('props').get('index') == custom_frame.get('frame_index')
                    ]), None)]), None),
                    captures.values()
                ), None)

                if is_already_used:
                    progress.update(task, advance=len(FILES))
                    console.print(f'[dark_orange] Custom frame selected (index: {custom_frame.get("frame_index")} - {Path(file.get("file")).name}) already used')
                    continue

                selected_frames = next(iter([grouped_frames for grouped_frames in frames if any([
                    frame.get('file') == file.get('file') and frame.get('props').get('index') == custom_frame.get('frame_index')
                    for frame in grouped_frames
                ])]), None)

                if not selected_frames:
                    progress.update(task, advance=len(FILES))
                    console.print(f'[dark_orange] Custom frame selected (index: {custom_frame.get("frame_index")} - {Path(file.get("file")).name}) not available')
                    continue

                capture = []

                for frame in selected_frames:
                    frame['capture'] = save_frame(frame.get('file'), frame.get('props'), captue_resolution)
                    capture.append(frame)
                    progress.update(task, advance=1)
                
                captures['custom'].append(capture)

    console.rule(style='cyan')

    if SLOWPICS_ENABLED:
        with Session() as session:
            console.print('[cyan]:books: Creating slowpics collection ...')

            if SLOWPICS_PROXY:
                session.proxies.update({'all': SLOWPICS_PROXY})

            fields = {
                'collectionName': SLOWPICS_COLLECTION,
                'public': 'true' if SLOWPICS_PUBLIC else 'false',
                'optimize-images': 'true',
                'hentai': 'true' if SLOWPICS_LIMITED else 'false',
                'browserId': str(uuid.uuid4()),
            }

            if SLOWPICS_EXPIRATION is not None:
                fields['removeAfter'] = str(SLOWPICS_EXPIRATION)

            images = []
            index = -1

            for capture_type in captures:
                capture_frames = captures[capture_type]

                if len(capture_frames) < 1:
                    continue

                for comp_images in capture_frames:
                    current_images = []
                    index += 1

                    fields[f'comparisons[{index}].name'] = f'{capture_type.capitalize()} scene'

                    for jndex, comp_image in enumerate(comp_images):
                        fields[f'comparisons[{index}].imageNames[{jndex}]'] = Path(comp_image.get('file')).name
                        current_images.append(comp_image)
                    
                    images.append(current_images)

            session.get('https://slow.pics/comparison')
            files = MultipartEncoder(fields, str(uuid.uuid4()))

            session.headers.update({
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'en-US,en;q=0.9',
                'Access-Control-Allow-Origin': '*',
                'Origin': 'https://slow.pics/',
                'Referer': 'https://slow.pics/comparison',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
            })

            req = session.post(
                'https://slow.pics/upload/comparison',
                data=files,
                headers={
                    'Content-Type': files.content_type,
                    'Content-Length': str(files.len),
                    'X-XSRF-TOKEN': session.cookies.get_dict().get('XSRF-TOKEN')
                }
            )
            
            req.raise_for_status()
            data = req.json()

            with Progress() as progress:
                task = progress.add_task('[cyan]:inbox_tray: Uploading images', total=len(images) * len(images[0]))

                images = []

                for _, captures in captures.items():
                    images += captures
                
                for index, images_chunk in enumerate(data.get('images')):
                    for jndex, image_id in enumerate(images_chunk):
                        image: Path = images[index][jndex].get('capture')

                        with image.open('rb') as f:
                            fields = {
                                "collectionUuid": data.get('collectionUuid'),
                                "imageUuid": image_id,
                                "file": (image.name, f, 'image/png'),
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

            slowpics_url = f'https://slow.pics/c/{data.get("key")}'
            console.print(f'[cyan]:link: Slowpics url: [link={slowpics_url}]{slowpics_url}[/link]')

            console.rule(style='cyan')

    with Progress() as progress:
        progress.add_task('[cyan]:broom: Cleanning temp files')

        for file in FILES:
            lwi = Path(f'{file.get("file")}.lwi')

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