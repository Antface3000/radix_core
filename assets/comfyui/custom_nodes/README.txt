BUNDLED COMFYUI CUSTOM NODES
============================

Drop the custom-node folders you want Radix Core to install here. Each subfolder
is copied into your ComfyUI install's custom_nodes/ directory by Service Setup
-> Sync Assets.

Example layout:

  assets/comfyui/custom_nodes/
      ComfyUI-KJNodes/
      rgthree-comfy/
      ComfyUI-GGUF/

Set your ComfyUI install path in the Service Setup panel first. Sync is
non-destructive: it merges into existing node folders (overwriting matching
files) and never deletes anything.
