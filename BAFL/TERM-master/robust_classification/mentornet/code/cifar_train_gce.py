# Copyright 2018 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Trains baseline models.

See the README.md file for compilation and running instructions.
"""

import os
import time
import cifar_data_provider
import inception_model
import resnet_model
import tensorflow as tf
import tensorflow.contrib.slim as slim

flags = tf.app.flags

flags.DEFINE_integer('batch_size', 128, 'The number of images in each batch.')

flags.DEFINE_string('master', None, 'BNS name of the TensorFlow master to use.')

flags.DEFINE_string('data_dir', '', 'Data dir')

flags.DEFINE_string('train_log_dir', '', 'Directory to the save trained model.')

flags.DEFINE_string('dataset_name', 'cifar10', 'cifar10 or cifar100')

flags.DEFINE_string('studentnet', 'resnet101', 'inception or resnet101')

flags.DEFINE_float('learning_rate', 0.1, 'The learning rate')
flags.DEFINE_float('learning_rate_decay_factor', 0.1,
                   'learning rate decay factor.')

flags.DEFINE_float('num_epochs_per_decay', 50,
                   'Number of epochs after which learning rate decays.')

flags.DEFINE_float('q', 0.8,
                   'q parameter for the generalized cross entropy loss')

flags.DEFINE_integer(
    'save_summaries_secs', 120,
    'The frequency with which summaries are saved, in seconds.')

flags.DEFINE_integer(
    'save_interval_secs', 1200,
    'The frequency with which the model is saved, in seconds.')

flags.DEFINE_integer('max_number_of_steps', 39000,
                     'The maximum number of gradient steps.')

flags.DEFINE_integer(
    'ps_tasks', 0,
    'The number of parameter servers. If the value is 0, then the parameters '
    'are handled locally by the worker.')

flags.DEFINE_integer(
    'task', 0,
    'The Task ID. This value is used when training with multiple workers to '
    'identify each worker.')

flags.DEFINE_string('device_id', '0', 'GPU device ID to run the job.')

FLAGS = flags.FLAGS

# turn this on if there are no log outputs
tf.logging.set_verbosity(tf.logging.INFO)


def train_inception_baseline(max_step_run):
  """Trains the inception baseline model.

  Args:
    max_step_run: The maximum number of gradient steps.
  """
  if not os.path.exists(FLAGS.train_log_dir):
    os.makedirs(FLAGS.train_log_dir)
  g = tf.Graph()

  with g.as_default():
    # If ps_tasks is zero, the local device is used. When using multiple
    # (non-local) replicas, the ReplicaDeviceSetter distributes the variables
    # across the different devices.
    with tf.device(tf.train.replica_device_setter(FLAGS.ps_tasks)):
      config = tf.ConfigProto()
      # Limit gpu memory to run train and eval on the same gpu
      config.gpu_options.per_process_gpu_memory_fraction = 0.45

      tf_global_step = tf.train.get_or_create_global_step()

      images, one_hot_labels, num_samples_per_epoch, num_of_classes = cifar_data_provider.provide_cifarnet_data(
          FLAGS.dataset_name,
          'train',
          FLAGS.batch_size,
          dataset_dir=FLAGS.data_dir)

      tf.logging.info('num_of_example={}'.format(num_samples_per_epoch))
      # Define the model:
      with slim.arg_scope(
          inception_model.cifarnet_arg_scope(weight_decay=0.004)):
        logits, _ = inception_model.cifarnet(
            images, num_of_classes, is_training=True, dropout_keep_prob=0.8)

      # Specify the loss function:
      #total_loss = tf.nn.softmax_cross_entropy_with_logits(
      #    labels=one_hot_labels, logits=logits)


      ## generalized cross-entropy loss
      logits = tf.nn.softmax(logits)  # default dimension is the last dimension
      _tmp = one_hot_labels * logits
      _loss = tf.reduce_max(_tmp, axis=-1)
      _q = tf.constant(FLAGS.q, dtype=tf.float32)
      _loss = (1 - (_loss + 10 ** (-8)) ** _q) / _q

      total_loss = tf.reduce_mean(_loss)


      # Using latest tensorflow ProtoBuf.
      tf.contrib.deprecated.scalar_summary('Total Loss', total_loss)

      decay_steps = int(
          num_samples_per_epoch / FLAGS.batch_size * FLAGS.num_epochs_per_decay)

      lr = tf.train.exponential_decay(
          FLAGS.learning_rate,
          tf_global_step,
          decay_steps,
          FLAGS.learning_rate_decay_factor,
          staircase=True)
      slim.summaries.add_scalar_summary(lr, 'learning_rate', print_summary=True)

      # Specify the optimization scheme:
      optimizer = tf.train.GradientDescentOptimizer(lr)

      # Set up training.
      train_op = slim.learning.create_train_op(total_loss, optimizer)

      # Run training.
      slim.learning.train(
          train_op=train_op,
          logdir=FLAGS.train_log_dir,
          master=FLAGS.master,
          is_chief=FLAGS.task == 0,
          session_config=config,
          number_of_steps=max_step_run,
          save_summaries_secs=FLAGS.save_summaries_secs,
          save_interval_secs=FLAGS.save_interval_secs)


def main(_):
  os.environ['CUDA_VISIBLE_DEVICES'] = FLAGS.device_id

  if FLAGS.studentnet == 'inception':
    train_inception_baseline(FLAGS.max_number_of_steps)
  else:
    tf.logging.error('unknown backbone student network %s', FLAGS.studentnet)


if __name__ == '__main__':
  tf.app.run()