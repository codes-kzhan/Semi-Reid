from reid.models import model_utils as mu
from reid.utils.data import data_process as dp
from reid.config import Config, TripletConfig
from reid.utils.osutils import mkdir_if_missing
from reid.utils.serialization import load_checkpoint, save_checkpoint
from reid import datasets
from reid import models
import numpy as np
import torch
import os
import argparse

parser=argparse.ArgumentParser(description='spaco arguments')
parser.add_argument('-s', '--seed', type=int, default=0)
args=parser.parse_args()


def spaco(configs,data,iter_step=1,gamma=0.3,train_ratio=0.2):
    """
    self-paced co-training model implementation based on Pytroch
    params:
    model_names: model names for spaco, such as ['resnet50','densenet121']
    data: dataset for spaco model
    save_pathts: save paths for two models
    iter_step: iteration round for spaco
    gamma: spaco hyperparameter
    train_ratio: initiate training dataset ratio
    """
    num_view = len(configs)
    train_data,untrain_data = dp.split_dataset(data.trainval, train_ratio, args.seed)
    data_dir = data.images_dir
    ###########
    # initiate classifier to get preidctions
    ###########

    add_ratio = 0.5
    pred_probs = []
    add_ids = []
    start_step = 0
    for view in range(num_view):
        if configs[view].checkpoint is None:
            model = mu.train(train_data, data_dir, configs[view])
            save_checkpoint({
                'state_dict': model.state_dict(),
                'epoch': 0,
                'train_data': train_data}, False,
                fpath = os.path.join(configs[view].logs_dir, configs[view].model_name, 'spaco.epoch0')
            )
        else:
            model = models.create(configs[view].model_name,
                                  num_features=configs[view].num_features,
                                  dropout=configs[view].dropout,
                                  num_classes=configs[view].num_classes)
            model = torch.nn.DataParallel(model).cuda()
            checkpoint = load_checkpoint(configs[view].checkpoint)
            model.load_state_dict(checkpoint['state_dict'])
            start_step = checkpoint['epoch']
            configs[view].set_training(False)
            add_ratio += start_step * 0.5
            # mu.evaluate(model, data, configs[view])
        pred_probs.append(mu.predict_prob(model, untrain_data, data_dir, configs[view]))
        add_ids.append(dp.sel_idx(pred_probs[view], train_data, add_ratio))
    pred_y = np.argmax(sum(pred_probs), axis=1)
    for step in range(start_step, iter_step):
        for view in range(num_view):
            # update v_view
            ov = add_ids[1 - view]
            pred_probs[view][ov,pred_y[ov]] += gamma
            add_id = dp.sel_idx(pred_probs[view],train_data, add_ratio)

            # update w_view
            new_train_data,_ = dp.update_train_untrain(add_id,train_data,untrain_data,pred_y)
            configs[view].set_training(True)
            model = mu.train(new_train_data, data_dir, configs[view])

            # update y
            pred_probs[view] = mu.predict_prob(model,untrain_data,data_dir, configs[view])
            pred_y = np.argmax(sum(pred_probs),axis=1)

            # udpate v_view for next view
            add_ratio += 0.5
            pred_probs[view][ov,pred_y[ov]] += gamma
            add_ids[view] = dp.sel_idx(pred_probs[view], train_data,add_ratio)


            # calculate predict probility on all data
            p_b = mu.predict_prob(model, data.trainval, data_dir, configs[view])
            p_y = np.argmax(p_b, axis=1)
            t_y = [c for (_,c,_,_) in data.trainval]
            print(np.mean(t_y == p_y))
#             evaluation current model and save it
            # mu.evaluate(model,data,configs[view])
            save_checkpoint({
                'state_dict': model.state_dict(),
                'epoch': step + 1,
                'train_data': new_train_data}, False,
                fpath=os.path.join(configs[view].logs_dir,
                                   configs[view].model_name,
                                   'spaco.epoch%d' % (step + 1))
            )
            # mkdir_if_missing(logs_pth)
            # torch.save(model.state_dict(), logs_pth +
            #           '/spaco.epoch%d' % (step + 1))

config1 = Config()
config2 = Config(model_name='densenet121', height=224, width=224)
dataset = 'market1501std'
cur_path = os.getcwd()
logs_dir = os.path.join(cur_path, 'logs')
data_dir = os.path.join(cur_path,'data',dataset)
data = datasets.create(dataset, data_dir)

spaco([config1,config2], data, 4)
