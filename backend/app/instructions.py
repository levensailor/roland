"""Official TM-2 load reminders. People forget these steps between sessions."""

from app.config import Settings
from app.models import InstructionSection, InstructionStep, InstructionsResponse


def build_instructions(settings: Settings) -> InstructionsResponse:
    wave_root = settings.wave_root
    rate = settings.sample_rate
    depth = settings.bit_depth
    max_files = settings.max_files_per_folder
    max_folders = settings.max_folders
    recommended = ", ".join(settings.default_folder_names)

    return InstructionsResponse(
        source="Roland TM-2 Owner's Manual and Roland Support article on WAV playback",
        format_rules=[
            f"Only WAV files play on the TM-2: {rate} Hz, {depth}-bit, mono or stereo.",
            "Extensions must be .wav or .WAV. MP3, M4A, AIFF, and FLAC will not play until converted.",
            "This app converts dropped files to clean PCM WAV and strips metadata tags that cause FORMAT errors.",
            f"Files must live at {wave_root} on the SD/SDHC card. One folder level inside WAVE is allowed.",
            f"Maximum {max_folders} folders. Maximum {max_files} files per folder. Deeper folders are ignored.",
            "ASCII names only. The TM-2 display garbles Japanese and other double-byte characters.",
            "Use an SD or SDHC card, 32 GB or smaller. Format it on the TM-2 the first time you use it.",
            "Keep this card dedicated to the TM-2. Cards shared with cameras or phones often fail.",
        ],
        sections=[
            InstructionSection(
                heading="1. Format a new card on the TM-2 first",
                steps=[
                    InstructionStep(
                        title="Power on with the card inserted",
                        detail=(
                            "Use a dedicated SD/SDHC card. Insert it while the TM-2 is off, then power on. "
                            "Formatting erases the card."
                        ),
                    ),
                    InstructionStep(
                        title="Open SD CARD FORMAT",
                        detail=(
                            "Hold SHIFT and press INST. Use < > to select SD CARD FORMAT, then press +. "
                            "Confirm with +, then press TRIG IN 2 to format."
                        ),
                    ),
                    InstructionStep(
                        title="Power off before removing the card",
                        detail=(
                            "Never insert or remove the card while the TM-2 is on. That leaves the FAT dirty "
                            "and macOS will remount the card read-only. Power off, then move the card here."
                        ),
                    ),
                ],
            ),
            InstructionSection(
                heading="2. Write samples with this app",
                steps=[
                    InstructionStep(
                        title="Select the mounted SD card",
                        detail=(
                            "Choose the volume in the card picker, or paste its path. "
                            f"This app creates {wave_root} and recommended folders: {recommended}."
                        ),
                    ),
                    InstructionStep(
                        title="Drop audio onto a folder",
                        detail=(
                            "Drag WAV, MP3, AIFF, FLAC, M4A, OGG, or similar onto a folder tile. "
                            f"Files convert to {rate} Hz / {depth}-bit PCM WAV with metadata stripped."
                        ),
                    ),
                    InstructionStep(
                        title="Eject, then insert with power off",
                        detail=(
                            "Eject the card from the computer. With the TM-2 powered off, insert the card. "
                            "User samples stream from the card, so it must stay inserted. NO CARD means it is missing."
                        ),
                    ),
                ],
            ),
            InstructionSection(
                heading="3. Assign each WAV to a pad",
                steps=[
                    InstructionStep(
                        title="Pick a kit",
                        detail="On the kit screen, use - + to choose the kit that should play the sample.",
                    ),
                    InstructionStep(
                        title="Open INST and select a pad",
                        detail=(
                            "Press INST. Strike the pad, or press TRIG IN 1 or 2. "
                            "Hold SHIFT and press a TRIG IN button to select the rim."
                        ),
                    ),
                    InstructionStep(
                        title="Jump to SD files",
                        detail=(
                            "Hold SHIFT and press - or + to jump between INT (internal) and SD. "
                            "If you made folders, SHIFT + -/+ also moves between folders. "
                            "Then use - + to pick the WAV. Folder names flash at the top of the display."
                        ),
                    ),
                    InstructionStep(
                        title="Save by leaving INST",
                        detail=(
                            "Strike the pad to audition. Press INST to return to the kit screen. "
                            "The assignment saves automatically. Repeat for the other pads."
                        ),
                    ),
                ],
            ),
            InstructionSection(
                heading="4. After you rename or move a file",
                steps=[
                    InstructionStep(
                        title="Reassign the pad",
                        detail=(
                            "The TM-2 stores a path, not a copy. If you rename, move, or delete a WAV, "
                            "the pad shows NO WAVE until you assign a file again."
                        ),
                    )
                ],
            ),
        ],
        error_codes=[
            InstructionStep(
                title="FORMAT",
                detail="Wrong file type or leftover DAW tags. Re-save through this app so the WAV is clean PCM.",
            ),
            InstructionStep(
                title="NO WAVE",
                detail="The assigned file is missing or was renamed. Reassign the pad after writing the card.",
            ),
            InstructionStep(
                title="NO CARD / NO SD CARD",
                detail="The card is not inserted. User samples will not play without the card in the slot.",
            ),
            InstructionStep(
                title="SD CARD LOCKED",
                detail="Slide the write-protect switch off LOCK before writing from this computer.",
            ),
            InstructionStep(
                title="SD CARD FULL / BUSY / ERROR",
                detail="Free space, try a different SD/SDHC card, or format the card on the TM-2 again.",
            ),
        ],
    )
