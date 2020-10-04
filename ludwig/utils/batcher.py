#! /usr/bin/env python
# coding=utf-8
# Copyright (c) 2019 Uber Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import math

import numpy as np
from ludwig.data.sampler import DistributedSampler


class Batcher(object):
    def __init__(self, dataset, sampler,
                 batch_size=128,
                 ignore_last=False):
        # store our dataset as well
        self.dataset = dataset
        self.sampler = sampler
        self.sample_it = iter(self.sampler)

        self.ignore_last = ignore_last
        self.batch_size = batch_size
        self.total_size = len(sampler)
        self.steps_per_epoch = int(
            math.ceil(self.total_size / self.batch_size))
        self.index = 0
        self.step = 0

    def next_batch(self):
        if self.last_batch():
            raise StopIteration()

        indices = []
        for _ in range(self.batch_size):
            try:
                indices.append(next(self.sample_it))
                self.index += 1
            except StopIteration:
                break

        sub_batch = {}
        for features_name in self.dataset.features:
            sub_batch[features_name] = self.dataset.get(
                features_name,
                indices
            )

        self.step += 1
        return sub_batch

    def last_batch(self):
        return self.index >= self.total_size or (
                self.ignore_last and
                self.index + self.batch_size >= self.total_size)

    def set_epoch(self, epoch):
        self.index = 0
        self.step = 0
        self.sampler.set_epoch(epoch)
        self.sample_it = iter(self.sampler)


class BucketedBatcher(object):
    def __init__(self, dataset, bucketing_field, batch_size=128, buckets=10,
                 should_shuffle=True, ignore_last=False,
                 should_trim=False, trim_side='right'):
        self.should_shuffle = should_shuffle
        self.bucketing_field = bucketing_field
        self.should_trim = should_trim
        self.trim_side = trim_side

        # store our dataset as well
        self.dataset = dataset

        field = dataset.get_dataset()[bucketing_field]
        field_lengths = np.apply_along_axis(lambda x: np.sign(x).sum(), 1,
                                            field)
        sorted_idcs = np.argsort(field_lengths)
        self.buckets_idcs = []
        datapoints_per_bucket = len(field) // buckets
        for b in range(buckets):
            start = datapoints_per_bucket * b
            end = datapoints_per_bucket * (b + 1) if b < buckets - 1 else len(
                sorted_idcs)
            self.buckets_idcs.append(sorted_idcs[start:end])

        if should_shuffle:
            self.shuffle(self.buckets_idcs)

        self.ignore_last = ignore_last
        self.batch_size = batch_size
        self.total_size = min(map(len, dataset.get_dataset().values()))
        self.bucket_sizes = np.array([x for x in map(len, self.buckets_idcs)])
        self.steps_per_epoch = int(
            np.asscalar(np.sum(np.ceil(self.bucket_sizes / self.batch_size))))
        self.indices = np.array([0] * buckets)
        self.step = 0
        self.epoch = 0

    def shuffle(self, buckets_idcs):
        for i in range(len(buckets_idcs)):
            np.random.shuffle(buckets_idcs[i])

    def next_batch(self):
        if self.last_batch():
            if self.should_shuffle:
                self.shuffle(self.buckets_idcs)
            self.reset()
            self.epoch += 1

        if self.ignore_last:
            idcs_below_size = self.indices + self.batch_size < self.bucket_sizes
        else:
            idcs_below_size = self.indices < self.bucket_sizes
        i = np.random.choice(
            np.arange(0, len(self.buckets_idcs))[idcs_below_size])

        selected_bucket = self.buckets_idcs[i]
        selected_idcs = selected_bucket[
                        self.indices[i]:self.indices[i] + self.batch_size]

        sub_batch = {}
        for key in self.dataset.get_dataset():
            if key == self.bucketing_field and self.should_trim:
                selected_samples = self.dataset.get(key, selected_idcs)
                max_length = np.sign(selected_samples).sum(axis=1).max()
                if self.trim_side == 'right':
                    sub_batch[key] = selected_samples[:, :max_length]
                elif self.trim_side == 'left':
                    sub_batch[key] = selected_samples[:, -max_length:]
                else:
                    raise ValueError('Invalid trim side:', self.trim_side)

            else:
                sub_batch[key] = self.dataset.get(key, selected_idcs)

        self.indices[i] += self.batch_size
        self.step += 1
        return sub_batch

    def last_batch(self):
        return not np.any(self.indices < self.bucket_sizes) \
               or (self.ignore_last and
                   not np.any(
                       self.indices + self.batch_size < self.bucket_sizes
                   ))

    def reset(self):
        self.indices = np.array([0] * len(self.buckets_idcs))
        self.step = 0


# todo future: reintroduce the bucketed batcher
# def initialize_batcher(dataset, batch_size=128, bucketing_field=None,
#                        input_features=None, preprocessing=None,
#                        should_shuffle=True, ignore_last=False, horovod=None):
#     if horovod:
#         batcher = DistributedBatcher(
#             dataset,
#             horovod.rank(),
#             horovod,
#             batch_size,
#             should_shuffle=should_shuffle,
#             ignore_last=ignore_last
#         )
#     elif bucketing_field is not None:
#         bucketing_feature = [
#             feature for feature in input_features if
#             feature[NAME] == bucketing_field
#         ]
#         if not bucketing_feature:
#             raise ValueError(
#                 'Bucketing field {} not present in input features'.format(
#                     bucketing_field
#                 )
#             )
#         else:
#             bucketing_feature = bucketing_feature[0]
#         should_trim = bucketing_feature[
#                           'encoder'] in dynamic_length_encoders
#         if 'preprocessing' in bucketing_feature:
#             trim_side = bucketing_feature['preprocessing']['padding']
#         else:
#             trim_side = preprocessing[bucketing_feature[TYPE]]['padding']
#
#         batcher = BucketedBatcher(
#             dataset,
#             bucketing_field=bucketing_field,
#             batch_size=batch_size,
#             buckets=10,
#             ignore_last=ignore_last,
#             should_shuffle=should_shuffle,
#             should_trim=should_trim,
#             trim_side=trim_side
#         )
#     else:
#         batcher = Batcher(
#             dataset,
#             batch_size,
#             should_shuffle=should_shuffle,
#             ignore_last=ignore_last
#         )
#     return batcher

def initialize_batcher(dataset, batch_size=128,
                       should_shuffle=True,
                       seed=0,
                       ignore_last=False,
                       horovod=None):
    sampler = DistributedSampler(len(dataset),
                                 shuffle=should_shuffle,
                                 seed=seed,
                                 horovod=horovod)
    batcher = Batcher(dataset,
                      sampler,
                      batch_size=batch_size,
                      ignore_last=ignore_last)
    return batcher
