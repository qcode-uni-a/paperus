import type { GpuStep } from '#lib/api/generated/types.gen.ts';

export const GPU_HELP =
	'https://github.com/qcode-uni-a/paperus/blob/main/docs/operations.md#on-an-nvidia-gpu';
export const ELSEWHERE_HELP =
	'https://github.com/qcode-uni-a/paperus/blob/main/docs/operations.md#on-another-machine';

export type GpuAdvice = {
	done: boolean;
	title: string;
	text: string;
	links: [string, string][];
	/** Said also once done. */
	doneText?: string;
};

/** Whether the machine learning service uses the machine's GPU, and if
 * not, what to change (on the start page and in the first setup). */
export function gpuAdvice(gpu: GpuStep): GpuAdvice {
	const links: [string, string][] = [[GPU_HELP, 'On an NVIDIA GPU']];
	const has = `This machine has a GPU, the ${gpu.card}`;
	const faster =
		'search by meaning, OCR and reranking run many times faster on it (embedding about 20 times)';
	switch (gpu.advice) {
		case 'in_use':
			return {
				done: true,
				title: 'Machine learning on the GPU',
				text: '',
				doneText: `Runs on the ${gpu.card}.`,
				links: []
			};
		case 'use_cuda_image':
			return {
				done: false,
				title: 'Use the GPU for machine learning',
				text: `${has}, but the ML service runs its CPU image. With the -cuda image, ${faster}.`,
				links: [...links, [ELSEWHERE_HELP, 'Or on another machine']]
			};
		case 'pass_gpu':
			return {
				done: false,
				title: 'Give the ML service the GPU',
				text: `${has}, but the ML service runs on the CPU${gpu.problem ? `: ${gpu.problem}` : ''}. Pass the GPU to its container (devices in compose.yaml).`,
				links
			};
		case 'update_driver':
			return {
				done: false,
				title: 'Update the NVIDIA driver',
				text: `${has}. The ML service's -cuda image needs NVIDIA's driver ${gpu.driver_needed} or newer; this machine has ${gpu.driver}.`,
				links
			};
		case 'install_driver':
			return {
				done: false,
				title: 'Install the NVIDIA driver',
				text: `${has}. With NVIDIA's driver (${gpu.driver_needed} or newer) and the ML service's -cuda image, ${faster}.`,
				links
			};
	}
}
