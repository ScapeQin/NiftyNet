# -*- coding: utf-8 -*-
import tensorflow as tf

from . import layer_util
from .activation import ActiLayer
from .base import TrainableLayer
from .convolution import ConvLayer
from .deconvolution import DeconvLayer
from .elementwise import ElementwiseLayer


class VNet(TrainableLayer):
    """
    implementation of V-Net:
      Milletari et al., "V-Net: Fully convolutional neural networks for
      volumetric medical image segmentation", 3DV '16
    """

    def __init__(self,
                 num_classes,
                 w_initializer=None,
                 w_regularizer=None,
                 b_initializer=None,
                 b_regularizer=None,
                 acti_type='relu',
                 name='VNet'):
        super(VNet, self).__init__(name=name)

        self.num_classes = num_classes
        self.n_features = [16, 32, 64, 128, 256]
        self.acti_type = acti_type

        self.initializers = {'w': w_initializer, 'b': b_initializer}
        self.regularizers = {'w': w_regularizer, 'b': b_regularizer}

        print 'using {}'.format(name)

    def layer_op(self, images, is_training, layer_id=-1):
        assert layer_util.check_spatial_dims(images, lambda x: x % 8 == 0)

        if layer_util.infer_spatial_rank(images) == 2:
            padded_images = tf.tile(images, [1, 1, 1, self.n_features[0]])
        elif layer_util.infer_spatial_rank(images) == 3:
            padded_images = tf.tile(images, [1, 1, 1, 1, self.n_features[0]])
        else:
            raise ValueError('not supported spatial rank of the input image')
        # downsampling  blocks
        res_1, down_1 = VNetBlock('DOWNSAMPLE', 1,
                                  self.n_features[0],
                                  self.n_features[1],
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  name='L1')(images, padded_images)
        res_2, down_2 = VNetBlock('DOWNSAMPLE', 2,
                                  self.n_features[1],
                                  self.n_features[2],
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  name='L2')(down_1, down_1)
        res_3, down_3 = VNetBlock('DOWNSAMPLE', 3,
                                  self.n_features[2],
                                  self.n_features[3],
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  name='L3')(down_2, down_2)
        res_4, down_4 = VNetBlock('DOWNSAMPLE', 3,
                                  self.n_features[3],
                                  self.n_features[4],
                                  name='L4')(down_3, down_3)
        # upsampling blocks
        _, up_4 = VNetBlock('UPSAMPLE', 3,
                            self.n_features[4],
                            self.n_features[4],
                            w_initializer=self.initializers['w'],
                            w_regularizer=self.regularizers['w'],
                            name='V_')(down_4, down_4)
        concat_r4 = ElementwiseLayer('CONCAT')(up_4, res_4)
        _, up_3 = VNetBlock('UPSAMPLE', 3,
                            self.n_features[4],
                            self.n_features[3],
                            w_initializer=self.initializers['w'],
                            w_regularizer=self.regularizers['w'],
                            name='R4')(concat_r4, up_4)
        concat_r3 = ElementwiseLayer('CONCAT')(up_3, res_3)
        _, up_2 = VNetBlock('UPSAMPLE', 3,
                            self.n_features[3],
                            self.n_features[2],
                            w_initializer=self.initializers['w'],
                            w_regularizer=self.regularizers['w'],
                            name='R3')(concat_r3, up_3)
        concat_r2 = ElementwiseLayer('CONCAT')(up_2, res_2)
        _, up_1 = VNetBlock('UPSAMPLE', 2,
                            self.n_features[2],
                            self.n_features[1],
                            w_initializer=self.initializers['w'],
                            w_regularizer=self.regularizers['w'],
                            name='R2')(concat_r2, up_2)
        # final class score
        concat_r1 = ElementwiseLayer('CONCAT')(up_1, res_1)
        _, output_tensor = VNetBlock('SAME', 1,
                                     self.n_features[1],
                                     self.num_classes,
                                     w_initializer=self.initializers['w'],
                                     w_regularizer=self.regularizers['w'],
                                     b_initializer=self.initializers['b'],
                                     b_regularizer=self.regularizers['b'],
                                     name='R1')(concat_r1, up_1)
        return output_tensor


SUPPORTED_OPS = {'DOWNSAMPLE', 'UPSAMPLE', 'SAME'}


class VNetBlock(TrainableLayer):
    def __init__(self,
                 func,
                 n_conv,
                 n_feature_chns,
                 n_output_chns,
                 w_initializer=None,
                 w_regularizer=None,
                 b_initializer=None,
                 b_regularizer=None,
                 acti_type='relu',
                 name='vnet_block'):
        super(VNetBlock, self).__init__(name=name)

        self.func = func.upper()
        assert self.func in SUPPORTED_OPS
        self.n_conv = n_conv
        self.n_feature_chns = n_feature_chns
        self.n_output_chns = n_output_chns
        self.acti_type = acti_type

        self.initializers = {'w': w_initializer, 'b': b_initializer}
        self.regularizers = {'w': w_regularizer, 'b': b_regularizer}

    def layer_op(self, main_flow, bypass_flow):
        for i in range(self.n_conv):
            main_flow = ConvLayer(name='conv_{}'.format(i),
                                  n_output_chns=self.n_feature_chns,
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  kernel_size=5)(main_flow)
            if i < self.n_conv - 1:  # no activation for the last conv layer
                main_flow = ActiLayer(
                    func=self.acti_type,
                    regularizer=self.regularizers['w'])(main_flow)
        res_flow = ElementwiseLayer('SUM')(main_flow, bypass_flow)

        if self.func == 'DOWNSAMPLE':
            main_flow = ConvLayer(name='downsample',
                                  n_output_chns=self.n_output_chns,
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  kernel_size=2, stride=2)(res_flow)
        elif self.func == 'UPSAMPLE':
            main_flow = DeconvLayer(name='upsample',
                                    n_output_chns=self.n_output_chns,
                                    w_initializer=self.initializers['w'],
                                    w_regularizer=self.regularizers['w'],
                                    kernel_size=2, stride=2)(res_flow)
        elif self.func == 'SAME':
            main_flow = ConvLayer(name='conv_1x1x1',
                                  n_output_chns=self.n_output_chns,
                                  w_initializer=self.initializers['w'],
                                  w_regularizer=self.regularizers['w'],
                                  b_initializer=self.initializers['b'],
                                  b_regularizer=self.regularizers['b'],
                                  kernel_size=1, with_bias=True)(res_flow)
        main_flow = ActiLayer(self.acti_type)(main_flow)
        print self
        return res_flow, main_flow
