# Loudness of every video

Measured 2026-10-30 on the players with `ffmpeg -af ebur128=peak=true`: 66 videos in `~/videos` (client1 and client2 have identical sets).

- **LUFS**: integrated loudness. The clips used in the show range from -24.0 to -7.5 LUFS, a 16.5 dB spread. That spread is why some scenes were too quiet and others too loud.
- **LRA**: loudness range (how much it swings between quiet and loud parts).
- **Peak**: true peak in dBFS. Above 0 means the file itself already clips.
- **Gain**: what the player applies to reach the -14 LUFS target (boost capped at +18 dB). Peaks that would go over -1 dBFS are caught by the limiter; **Limited** is roughly how much the loudest peak gets pulled down.

| Clip | LUFS | LRA | Peak | Gain | Limited | Length | Used in |
|---|---:|---:|---:|---:|---:|---:|---|
| `Bone Chillers - Jittery Bones/Doorway - Horizontal/BC_Buffer_Holl_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Jittery Bones/Doorway - Vertical/BC_Buffer_Holl_V.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Jittery Bones/TV/BC_Buffer_TV_H.mp4` | silent | 0.0 | — | — | — | 0:20 |  |
| `Bone Chillers - Jittery Bones/Wall/BC_Buffer_Wall_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Jittery Bones/Window - Black BG/BC_Buffer_Win_Black_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Jittery Bones/Window - Shadow/BC_Buffer_Win_Shad_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Numskulls/TV/BC_Buffer_TV_H.mp4` | silent | 0.0 | — | — | — | 0:20 |  |
| `Bone Chillers - Numskulls/Wall/BC_Buffer_Wall_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Numskulls/Window - Black BG/BC_Buffer_Win_Black_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `Bone Chillers - Numskulls/Window - Shadow/BC_Buffer_Win_Shad_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `TnT - Vampire Scenes - Window/TnT_Buffer_Win_H.mp4` | silent | 0.0 | — | — | — | 0:10 |  |
| `WH - Song1 - Witching Hour - Hollusion-TV-Window/WH_Buffer_Black_H.mp4` | silent | 0.0 | — | — | — | 0:15 |  |
| `WH - Song2 - Cat Crow Canzonet - Hollusion-TV-Window/WH_Buffer_Black_H.mp4` | silent | 0.0 | — | — | — | 0:15 |  |
| `WH - Spell2 - Wicked Brew - Hollusion+TV+Window/WH_Buffer_Black_H.mp4` | silent | 0.0 | — | — | — | 0:15 |  |
| `WH - Spell3 - Seance - Hollusion-TV-Window/WH_Buffer_Black_H.mp4` | silent | 0.0 | — | — | — | 0:15 |  |
| `Jack-O-Lantern - Stories - Window/Jack-O-Lantern - Stories - Window/JOLJ_TwasTheNight_Trio_Win_BG_H.mp4` | -24.0 | 5.0 | -5.7 | +10.0 dB | 5.3 dB | 1:32 | Twas the Night (P1 master) |
| `Jack-O-Lantern - Stories - Window/Jack-O-Lantern - Stories - Window/JOLJ_TwasTheNight_Trio_Win_Black_H.mp4` | -24.0 | 5.0 | -5.7 | +10.0 dB | 5.3 dB | 1:32 |  |
| `Ghostly Apparitions-Beckoning Beauty.mp4` | -23.2 | 14.8 | -2.8 | +9.2 dB | 7.4 dB | 2:20 | Seance (P1) |
| `Ghostbusters_LilJon-clean.mp4` | -23.1 | 4.4 | -10.5 | +9.1 dB |  | 4:38 | Ghostbusters (P2 master) |
| `Ghostbusters_LilJon.mp4` | -23.0 | 4.4 | -10.6 | +9.0 dB |  | 4:38 |  |
| `Jack-O-Lantern - Stories - Window/Jack-O-Lantern - Stories - Window/JOLJ_3ChildrenBold_Trio_Win_BG_H.mp4` | -22.9 | 6.1 | -4.5 | +8.9 dB | 5.4 dB | 2:23 |  |
| `Jack-O-Lantern - Stories - Window/Jack-O-Lantern - Stories - Window/JOLJ_3ChildrenBold_Trio_Win_Black_H.mp4` | -22.9 | 6.1 | -4.5 | +8.9 dB | 5.4 dB | 2:23 |  |
| `Zombie Invasion-Swarm.mp4` | -22.7 | 3.8 | -7.4 | +8.7 dB | 2.3 dB | 1:35 |  |
| `Bone Chillers - Numskulls/Wall/BC_Numskulls_Wall_H.mp4` | -22.2 | 24.7 | -0.4 | +8.2 dB | 8.8 dB | 0:45 | Pumpkin Song (P2) |
| `Bone Chillers - Numskulls/Window - Black BG/BC_Numskulls_Win_Black_H.mp4` | -22.2 | 24.7 | -0.4 | +8.2 dB | 8.8 dB | 0:45 |  |
| `Bone Chillers - Numskulls/Window - Shadow/BC_Numskulls_Win_Shad_H.mp4` | -22.2 | 24.7 | -0.4 | +8.2 dB | 8.8 dB | 0:45 |  |
| `Bone Chillers - Numskulls/TV/BC_Numskulls_TV_H.mp4` | -21.8 | 21.3 | -0.4 | +7.8 dB | 8.4 dB | 0:35 |  |
| `Jack-O-Lantern - Songs - Window/Jack-O-Lantern - Songs - Window/JOLJ_PumpkinSong_Trio_Win_BG_H.mp4` | -20.5 | 13.9 | -2.5 | +6.5 dB | 5.0 dB | 1:51 | Pumpkin Song (P1 master) |
| `Jack-O-Lantern - Songs - Window/Jack-O-Lantern - Songs - Window/JOLJ_PumpkinSong_Trio_Win_Black_H.mp4` | -20.5 | 13.9 | -2.5 | +6.5 dB | 5.0 dB | 1:51 |  |
| `TnT - Vampire Scenes - Window/TnT_GoingBatty_Win_H.mp4` | -20.1 | 11.1 | -2.2 | +6.1 dB | 4.9 dB | 0:22 |  |
| `EE_OminousOculi_Swarm_Eyes+Mouths_H.mp4` | -19.1 | 4.1 | -0.3 | +5.1 dB | 5.8 dB | 1:15 | Dragula APT (P2); In the Hall (P2); Ghostbusters (P1); Guardians Inferno (P2) |
| `Jack-O-Lantern - Songs - Window/Jack-O-Lantern - Songs - Window/JOLJ_InTheHallSong_Trio_Win_BG_H.mp4` | -18.9 | 14.9 | -0.5 | +4.9 dB | 5.4 dB | 1:55 | In the Hall (P1 master) |
| `Jack-O-Lantern - Songs - Window/Jack-O-Lantern - Songs - Window/JOLJ_InTheHallSong_Trio_Win_Black_H.mp4` | -18.9 | 14.9 | -0.5 | +4.9 dB | 5.4 dB | 1:55 |  |
| `Tricks and Treats-Frankenstein.mp4` | -18.8 | 20.0 | -0.0 | +4.8 dB | 5.8 dB | 1:36 | Frankenstein (P1 master) |
| `deadmou5_ghostsnstuff.mp4` | -18.8 | 2.2 | -8.2 | +4.8 dB |  | 3:14 | Ghosts n Stuff (P2 master) |
| `Jack-O-Lantern - Funny Faces - Window/Jack-O-Lantern - Funny Faces - Window/JOLJ_FunnyFaces_Trio_Win_BG_H.mp4` | -18.1 | 18.0 | -2.2 | +4.1 dB | 2.9 dB | 1:00 | Wicked Brew (P1); Ghosts n Stuff (P1) |
| `Jack-O-Lantern - Funny Faces - Window/Jack-O-Lantern - Funny Faces - Window/JOLJ_FunnyFaces_Trio_Win_Black_H.mp4` | -18.1 | 18.0 | -2.2 | +4.1 dB | 2.9 dB | 1:00 |  |
| `BOO_BooTime_Holl_H.mp4` | -18.0 | 17.7 | -2.9 | +4.0 dB | 2.1 dB | 0:52 | Witching Hour (P1) |
| `WH - Spell3 - Seance - Hollusion-TV-Window/WH_Spell 3_Seance_Holl_H.mp4` | -17.9 | 10.0 | -1.5 | +3.9 dB | 3.4 dB | 2:33 | Seance (P2 master) |
| `Bone Chillers-Dancing Dead.mp4` | -17.7 | 10.9 | -4.2 | +3.7 dB | 0.5 dB | 1:12 | Spooky Scary Skeletons (P1) |
| `Phantasms-Rise Of The Wraiths.mp4` | -17.6 | 14.4 | -1.3 | +3.6 dB | 3.3 dB | 0:53 | Frankenstein (P2) |
| `WH - Spell3 - Seance - Hollusion-TV-Window/WH_Spell 3_Seance_TV_H.mp4` | -17.6 | 10.5 | -1.4 | +3.6 dB | 3.2 dB | 2:33 |  |
| `WH - Spell3 - Seance - Hollusion-TV-Window/WH_Spell 3_Seance_Win_H.mp4` | -17.6 | 10.5 | -1.4 | +3.6 dB | 3.2 dB | 2:33 |  |
| `TnT - Vampire Scenes - Window/TnT_BatsAndBrooms_Win_H.mp4` | -17.2 | 22.9 | -3.4 | +3.2 dB | 0.8 dB | 0:31 | Cat Crow Canzonet (P1) |
| `WH - Spell2 - Wicked Brew - Hollusion+TV+Window/WH_Spell 2_WickedBrew_Holl_H.mp4` | -17.0 | 10.2 | -2.7 | +3.0 dB | 1.3 dB | 2:17 | Wicked Brew (P2 master) |
| `WH - Spell2 - Wicked Brew - Hollusion+TV+Window/WH_Spell 2_WickedBrew_TV_H.mp4` | -16.3 | 8.9 | -2.4 | +2.3 dB | 0.9 dB | 2:17 |  |
| `WH - Spell2 - Wicked Brew - Hollusion+TV+Window/WH_Spell 2_WickedBrew_Win_H.mp4` | -16.3 | 8.9 | -2.4 | +2.3 dB | 0.9 dB | 2:17 |  |
| `YTDown.com_YouTube_Eminem-&-Steve-Miller-Houdini-Abracadabr_Media_Yi0QxyxDkB4_001_1080p.mp4` | -15.7 | 2.5 | -1.6 | +1.7 dB | 1.1 dB | 5:53 |  |
| `WH - Song2 - Cat Crow Canzonet - Hollusion-TV-Window/WH_Song 2_CatCrow_Holl_H.mp4` | -15.2 | 11.3 | -2.2 | +1.2 dB |  | 1:21 | Cat Crow Canzonet (P2 master) |
| `WH - Song2 - Cat Crow Canzonet - Hollusion-TV-Window/WH_Song 2_CatCrow_TV_H.mp4` | -15.2 | 11.3 | -2.2 | +1.2 dB |  | 1:21 |  |
| `WH - Song2 - Cat Crow Canzonet - Hollusion-TV-Window/WH_Song 2_CatCrow_Win_H.mp4` | -15.2 | 11.3 | -2.2 | +1.2 dB |  | 1:21 |  |
| `DJ-Cummerbund-Play-That-Funky-Music-Ramm.mp4` | -14.9 | 4.3 | -0.5 | +0.9 dB | 1.4 dB | 3:36 |  |
| `Thriller/thriller_video.mp4` | -14.6 | 15.6 | -1.3 | +0.6 dB | 0.3 dB | 13:42 | Thriller (P1 master) |
| `WH - Song1 - Witching Hour - Hollusion-TV-Window/WH_Song 1_WitchingHour_Holl_H.mp4` | -14.5 | 5.0 | -0.5 | +0.5 dB | 1.0 dB | 2:13 | Witching Hour (P2 master) |
| `WH - Song1 - Witching Hour - Hollusion-TV-Window/WH_Song 1_WitchingHour_TV_H.mp4` | -14.5 | 5.0 | -0.5 | +0.5 dB | 1.0 dB | 2:13 |  |
| `WH - Song1 - Witching Hour - Hollusion-TV-Window/WH_Song 1_WitchingHour_Win_H.mp4` | -14.5 | 5.0 | -0.5 | +0.5 dB | 1.0 dB | 2:13 |  |
| `Bone Chillers - Jittery Bones/Doorway - Horizontal/BC_JitteryBones_Holl_H.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 |  |
| `Bone Chillers - Jittery Bones/Doorway - Vertical/BC_JitteryBones_Holl_V.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 |  |
| `Bone Chillers - Jittery Bones/TV/BC_JitteryBones_TV_H.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 |  |
| `Bone Chillers - Jittery Bones/Wall/BC_JitteryBones_Wall_H.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 | Twas the Night (P2) |
| `Bone Chillers - Jittery Bones/Window - Black BG/BC_JitteryBones_Win_Black_H.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 |  |
| `Bone Chillers - Jittery Bones/Window - Shadow/BC_JitteryBones_Win_Shad_H.mp4` | -14.1 | 23.0 | 0.4 | +0.1 dB | 1.5 dB | 0:28 |  |
| `Guardians_inferno.mp4` | -10.8 | 3.3 | -1.6 | -3.2 dB |  | 3:38 | Guardians Inferno (P1 master) |
| `DJ-Cummerbund-DragulAPT.mp4` | -10.6 | 2.5 | 0.8 | -3.4 dB |  | 4:39 | Dragula APT (P1 master) |
| `Thriller/thriller_anim.mp4` | -9.4 | 13.1 | 2.5 | -4.6 dB |  | 6:43 | Thriller (P2) |
| `Spooly Scarry Skel.mp4` | -7.5 | 2.2 | 1.4 | -6.5 dB |  | 3:50 | Spooky Scary Skeletons (P2 master) |

## In show.yaml but not on the players

None: every clip the show uses is on both players.

## On the players but not used in the show

- `DJ-Cummerbund-Play-That-Funky-Music-Ramm.mp4`
- `Ghostbusters_LilJon.mp4`
- `Jack-O-Lantern - Stories - Window/Jack-O-Lantern - Stories - Window/JOLJ_3ChildrenBold_Trio_Win_BG_H.mp4`
- `YTDown.com_YouTube_Eminem-&-Steve-Miller-Houdini-Abracadabr_Media_Yi0QxyxDkB4_001_1080p.mp4`
- `Zombie Invasion-Swarm.mp4`
