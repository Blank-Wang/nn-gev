import argparse
import numpy as np
from chainer import cuda
from chainer import serializers
from tqdm import tqdm
import os
from chainer import Variable
from fgnt.utils import mkdir_p

from chime_data import gen_flist_simu,\
    gen_flist_real, get_audio_data, get_audio_data_with_context
from nn_models import BLSTMMaskEstimator
from fgnt.signal_processing import audiowrite, stft, istft
from fgnt.beamforming import gev_wrapper_on_masks

parser = argparse.ArgumentParser(description='NN GEV beamforming')
parser.add_argument('chime_dir',
                    help='Base directory of the CHiME challenge. This is '
                         'used to create the training data. If not specified, '
                         'the data_dir must contain some training data.')
parser.add_argument('output_dir',
                    help='The directory where the enhanced wav files will '
                         'be stored.')
parser.add_argument('model',
                    help='Trained model file')
parser.add_argument('flist',
                    help='Name of the flist to process (e.g. tr05_simu')
parser.add_argument('--gpu', '-g', default=-1, type=int,
                    help='GPU ID (negative value indicates CPU)')
args = parser.parse_args()

# Prepare model
model = BLSTMMaskEstimator()
serializers.load_hdf5(args.model, model)
if args.gpu >= 0:
    cuda.get_device(args.gpu).use()
    model.to_gpu()
xp = np if args.gpu < 0 else cuda.cupy

stage = args.flist[:2]
scenario = args.flist.split('_')[-1]

if scenario == 'simu':
    flist = gen_flist_simu(args.chime_dir, stage)
elif scenario == 'real':
    flist = gen_flist_real(args.chime_dir, stage)
else:
    raise ValueError('Unknown flist {}'.format(args.flist))

for env in ['caf', 'bus', 'str', 'ped']:
    mkdir_p(os.path.join(args.output_dir, '{}05_{}_{}'.format(
        stage, env, scenario
    )))

# Beamform loop
for cur_line in tqdm(flist):
    if scenario == 'simu':
        audio_data = get_audio_data(cur_line)
        context_frames = 0
    elif scenario == 'real':
        audio_data, context_frames = get_audio_data_with_context(
                cur_line[0], cur_line[1], cur_line[2])
    Y = stft(audio_data, time_dim=1).transpose((1, 0, 2))
    Y_var = Variable(np.abs(Y).astype(np.float32), True)
    if args.gpu >= 0:
        Y_var.to_gpu(args.gpu)
    N_masks, X_masks = model.calc_masks(Y_var)
    N_masks.to_cpu()
    X_masks.to_cpu()
    N_mask = np.median(N_masks.data, axis=1)
    X_mask = np.median(X_masks.data, axis=1)
    Y_hat = gev_wrapper_on_masks(Y, N_mask, X_mask)



    if scenario == 'simu':
        wsj_name = cur_line.split('/')[-1].split('_')[1]
        spk = cur_line.split('/')[-1].split('_')[0]
        env = cur_line.split('/')[-1].split('_')[-1]
    elif scenario == 'real':
        wsj_name = cur_line[3]
        spk = cur_line[0].split('/')[-1].split('_')[0]
        env = cur_line[0].split('/')[-1].split('_')[-1]

    filename = os.path.join(
        args.output_dir,
    '{}05_{}_{}'.format(stage, env.lower(), scenario),
    '{}_{}_{}.wav'.format(spk, wsj_name, env.upper())
    )
    audiowrite(istft(Y_hat), filename, 16000, True, True)