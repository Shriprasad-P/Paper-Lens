"""Isolated MLX process so a Metal failure cannot terminate the API."""

from __future__ import annotations

import contextlib
import json
import sys


def main() -> None:
    request = json.load(sys.stdin)
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_image

    with contextlib.redirect_stdout(sys.stderr):
        model, processor = load(request["model"])
        prompt = apply_chat_template(processor, model.config, request["prompt"], num_images=1)
        result = generate(
            model,
            processor,
            image=[load_image(request["image"])],
            prompt=prompt,
            max_tokens=700,
            temperature=0.0,
            top_p=1.0,
            repetition_penalty=1.05,
        )
    print(result.text if hasattr(result, "text") else str(result))


if __name__ == "__main__":
    main()
