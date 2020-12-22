import torch
import math
from UnarySim.sw.stream.gen import RNG, RNGMulti, SourceGen, BSGen, BSGenMulti

class UnaryLinear(torch.nn.Module):
    """
    this module is the fully connected layer,
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) accumulation mode
    2) unary data mode
    3) binary data width
    4) binary weight
    5) binary bias
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 binary_weight=None, 
                 binary_bias=None, 
                 bitwidth=8, 
                 bias=True, 
                 mode="bipolar", 
                 scaled=True, 
                 btype=torch.float, 
                 rtype=torch.float, 
                 stype=torch.float):
        super(UnaryLinear, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.stype = stype
        self.btype = btype
        self.rtype = rtype
        
        # upper bound for accumulation counter in scaled mode
        self.acc_bound = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        self.acc_bound.add_(in_features)
        if bias is True:
            self.acc_bound.add_(1)
            
        self.mode = mode
        self.scaled = scaled
        
        # accumulation offset
        self.offset = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if mode == "unipolar":
            pass
        elif mode == "bipolar":
            self.offset.add_((in_features-1)/2)
            if bias is True:
                self.offset.add_(1/2)
        else:
            raise ValueError("UnaryLinear mode is not implemented.")
        
        # bias indication for original linear layer
        self.has_bias = bias
        
        # data bit width
        self.bitwidth = bitwidth
        
        # random_sequence from sobol RNG
        self.rng = RNG(self.bitwidth, 1, "Sobol")()
        
        # define the convolution weight and bias
        self.buf_wght = SourceGen(binary_weight, bitwidth=self.bitwidth, mode=mode, rtype=rtype)()
        if self.has_bias is True:
            self.buf_bias = SourceGen(binary_bias, bitwidth=self.bitwidth, mode=mode, rtype=rtype)()

        # define the kernel linear
        self.kernel = torch.nn.Linear(self.in_features, self.out_features, bias=self.has_bias)
        self.buf_wght_bs = BSGen(self.buf_wght, self.rng, stype=stype)
        self.rng_wght_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.weight, dtype=torch.long), requires_grad=False)
        if self.has_bias is True:
            self.buf_bias_bs = BSGen(self.buf_bias, self.rng, stype=stype)
            self.rng_bias_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel with inverse input, note that there is no bias required for this inverse kernel
        if self.mode == "bipolar":
            self.kernel_inv = torch.nn.Linear(self.in_features, self.out_features, bias=False)
            self.buf_wght_bs_inv = BSGen(self.buf_wght, self.rng, stype=stype)
            self.rng_wght_idx_inv = torch.nn.Parameter(torch.zeros_like(self.kernel_inv.weight, dtype=torch.long), requires_grad=False)

        self.accumulator = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if self.scaled is False:
            self.out_accumulator = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def UnaryKernel_accumulation(self, input):
        # generate weight and bias bits for current cycle
        self.kernel.weight.data = self.buf_wght_bs(self.rng_wght_idx).type(torch.float)
        self.rng_wght_idx.add_(input.type(torch.long))
        if self.has_bias is True:
            self.kernel.bias.data = self.buf_bias_bs(self.rng_bias_idx).type(torch.float)
            self.rng_bias_idx.add_(1)
            
        kernel_out = self.kernel(input.type(torch.float))

        if self.mode == "unipolar":
            return kernel_out
        
        if self.mode == "bipolar":
            self.kernel_inv.weight.data = 1 - self.buf_wght_bs_inv(self.rng_wght_idx_inv).type(torch.float)
            self.rng_wght_idx_inv.add_(1 - input.type(torch.long))
            kernel_out_inv = self.kernel_inv(1 - input.type(torch.float))
            return kernel_out + kernel_out_inv

    def forward(self, input):
        kernel_out_total = self.UnaryKernel_accumulation(input)
        self.accumulator.data = self.accumulator.add(kernel_out_total)
        if self.scaled is True:
            output = torch.ge(self.accumulator, self.acc_bound).type(torch.float)
            self.accumulator.sub_(output * self.acc_bound)
        else:
            self.accumulator.sub_(self.offset)
            output = torch.gt(self.accumulator, self.out_accumulator).type(torch.float)
            self.out_accumulator.data = self.out_accumulator.add(output)

        return output.type(self.stype)
        
        
class GainesLinear1(torch.nn.Module):
    """
    gMUL + gADD
    this module is the fully connected layer,
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) accumulation mode
    2) unary data mode
    3) binary data width
    4) binary weight
    5) binary bias
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 binary_weight=None, 
                 binary_bias=None, 
                 bitwidth=8, 
                 bias=True, 
                 mode="bipolar", 
                 scaled=True, 
                 depth=8, 
                 rng_idx=1):
        super(GainesLinear1, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        
        # upper bound for accumulation counter in non-scaled mode
        self.acc_bound = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        self.acc_bound.add_(in_features)
        if bias is True:
            self.acc_bound.add_(1)
            
        self.mode = mode
        self.scaled = scaled
        
        # accumulation offset
        self.offset = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if mode == "unipolar":
            pass
        elif mode == "bipolar":
            self.offset.add_((in_features-1)/2)
            if bias is True:
                self.offset.add_(1/2)
        else:
            raise ValueError("UnaryLinear mode is not implemented.")
        
        # bias indication for original linear layer
        self.has_bias = bias
        
        # data bit width
        self.bitwidth = bitwidth
        
        # random_sequence from sobol RNG
        self.rng = RNGMulti(self.bitwidth, in_features, "Sobol")()
        self.rng_bias = RNG(self.bitwidth, in_features+1, "Sobol")()
        
        # define the convolution weight and bias
        self.buf_wght = SourceGen(binary_weight, bitwidth=self.bitwidth, mode=mode)()
        if self.has_bias is True:
            self.buf_bias = SourceGen(binary_bias, bitwidth=self.bitwidth, mode=mode)()
        
        # define the kernel linear
        self.kernel = torch.nn.Linear(self.in_features, self.out_features, bias=self.has_bias)
        self.buf_wght_bs = BSGenMulti(self.buf_wght, self.rng, dim=0)
        self.rng_wght_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.weight, dtype=torch.long), requires_grad=False)
        if self.has_bias is True:
            self.buf_bias_bs = BSGen(self.buf_bias, self.rng_bias)
            self.rng_bias_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel with inverse input, note that there is no bias required for this inverse kernel
        if self.mode == "bipolar":
            self.kernel_inv = torch.nn.Linear(self.in_features, self.out_features, bias=False)

        self.parallel_cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        
        if self.scaled is True:
            self.rng_scale = RNG(round(math.log2(self.acc_bound.item())), (rng_idx+5)%1111, "Sobol")()
            self.rng_scale_idx = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        elif self.scaled is False:
            self.input_cnt = self.acc_bound.item()
            self.max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**depth-1), requires_grad=False)
            self.half_max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            self.cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            
    def GainesKernel_accumulation(self, input):
        # generate weight and bias bits for current cycle
        self.kernel.weight.data = self.buf_wght_bs(self.rng_wght_idx).type(torch.float)
        self.rng_wght_idx.add_(1)
        if self.has_bias is True:
            self.kernel.bias.data = self.buf_bias_bs(self.rng_bias_idx).type(torch.float)
            self.rng_bias_idx.add_(1)
            
        kernel_out = self.kernel(input.type(torch.float))

        if self.mode == "unipolar":
            return kernel_out
        
        if self.mode == "bipolar":
            self.kernel_inv.weight.data = 1 - self.kernel.weight.data
            kernel_out_inv = self.kernel_inv(1 - input.type(torch.float))
            return kernel_out + kernel_out_inv

    def forward(self, input):
        self.parallel_cnt.data = self.GainesKernel_accumulation(input).type(torch.long)

        if self.scaled is True:
            output = torch.ge(self.parallel_cnt.data, self.rng_scale[self.rng_scale_idx%len(self.rng_scale)])
            self.rng_scale_idx.add_(1)
        else:
            if self.mode == "unipolar":
                output = torch.gt(self.parallel_cnt, 0)
            elif self.mode == "bipolar":
                self.parallel_cnt.mul_(2).sub_(self.input_cnt)
                self.cnt.data = self.cnt.add(self.parallel_cnt).clamp(0, self.max.item())
                output = torch.gt(self.cnt, self.half_max)

        return output.type(torch.int8)
    
    
class GainesLinear2(torch.nn.Module):
    """
    gMUL + uADD
    this module is the fully connected layer,
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) accumulation mode
    2) unary data mode
    3) binary data width
    4) binary weight
    5) binary bias
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 binary_weight=None, 
                 binary_bias=None, 
                 bitwidth=8, 
                 bias=True, 
                 mode="bipolar", 
                 scaled=True, 
                 depth=8, 
                 rng_idx=1):
        super(GainesLinear2, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        
        # upper bound for accumulation counter in non-scaled mode
        self.acc_bound = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        self.acc_bound.add_(in_features)
        if bias is True:
            self.acc_bound.add_(1)
            
        self.mode = mode
        self.scaled = scaled
        
        # accumulation offset
        self.offset = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if mode == "unipolar":
            pass
        elif mode == "bipolar":
            self.offset.add_((in_features-1)/2)
            if bias is True:
                self.offset.add_(1/2)
        else:
            raise ValueError("UnaryLinear mode is not implemented.")
        
        # bias indication for original linear layer
        self.has_bias = bias
        
        # data bit width
        self.bitwidth = bitwidth
        
        # random_sequence from sobol RNG
        self.rng = RNGMulti(self.bitwidth, in_features, "Sobol")()
        self.rng_bias = RNG(self.bitwidth, in_features+1, "Sobol")()
        
        # define the convolution weight and bias
        self.buf_wght = SourceGen(binary_weight, bitwidth=self.bitwidth, mode=mode)()
        if self.has_bias is True:
            self.buf_bias = SourceGen(binary_bias, bitwidth=self.bitwidth, mode=mode)()
        
        # define the kernel linear
        self.kernel = torch.nn.Linear(self.in_features, self.out_features, bias=self.has_bias)
        self.buf_wght_bs = BSGenMulti(self.buf_wght, self.rng, dim=0)
        self.rng_wght_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.weight, dtype=torch.long), requires_grad=False)
        if self.has_bias is True:
            self.buf_bias_bs = BSGen(self.buf_bias, self.rng_bias)
            self.rng_bias_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel with inverse input, note that there is no bias required for this inverse kernel
        if self.mode == "bipolar":
            self.kernel_inv = torch.nn.Linear(self.in_features, self.out_features, bias=False)
        
        self.accumulator = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if self.scaled is False:
            self.out_accumulator = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
            
    def GainesKernel_accumulation(self, input):
        # generate weight and bias bits for current cycle
        self.kernel.weight.data = self.buf_wght_bs(self.rng_wght_idx).type(torch.float)
        self.rng_wght_idx.add_(1)
        if self.has_bias is True:
            self.kernel.bias.data = self.buf_bias_bs(self.rng_bias_idx).type(torch.float)
            self.rng_bias_idx.add_(1)
            
        kernel_out = self.kernel(input.type(torch.float))

        if self.mode == "unipolar":
            return kernel_out
        
        if self.mode == "bipolar":
            self.kernel_inv.weight.data = 1 - self.kernel.weight.data
            kernel_out_inv = self.kernel_inv(1 - input.type(torch.float))
            return kernel_out + kernel_out_inv

    def forward(self, input):
        if self.scaled is True:
            self.accumulator.data = self.accumulator.add(self.GainesKernel_accumulation(input))
            output = torch.ge(self.accumulator, self.acc_bound).type(torch.float)
            self.accumulator.sub_(output * self.acc_bound)
        else:
            self.accumulator.data = self.accumulator.add(self.GainesKernel_accumulation(input))
            self.accumulator.sub_(self.offset)
            output = torch.gt(self.accumulator, self.out_accumulator).type(torch.float)
            self.out_accumulator.data = self.out_accumulator.add(output)

        return output.type(torch.int8)
    

class GainesLinear3(torch.nn.Module):
    """
    uMUL + gADD: this version will not work well, due to same rng is used in uMUL, the accumulation
    will be inaccurate.
    this module is the fully connected layer,
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) accumulation mode
    2) unary data mode
    3) binary data width
    4) binary weight
    5) binary bias
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 binary_weight=None, 
                 binary_bias=None, 
                 bitwidth=8, 
                 bias=True, 
                 mode="bipolar", 
                 scaled=True, 
                 depth=8, 
                 rng_idx=1):
        super(GainesLinear3, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        
        # upper bound for accumulation counter in non-scaled mode
        self.acc_bound = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        self.acc_bound.add_(in_features)
        if bias is True:
            self.acc_bound.add_(1)
            
        self.mode = mode
        self.scaled = scaled
        
        # accumulation offset
        self.offset = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if mode == "unipolar":
            pass
        elif mode == "bipolar":
            self.offset.add_((in_features-1)/2)
            if bias is True:
                self.offset.add_(1/2)
        else:
            raise ValueError("UnaryLinear mode is not implemented.")
        
        # bias indication for original linear layer
        self.has_bias = bias
        
        # data bit width
        self.bitwidth = bitwidth
        
        # random_sequence from sobol RNG
        self.rng = RNG(self.bitwidth, 1, "Sobol")()
        
        # define the convolution weight and bias
        self.buf_wght = SourceGen(binary_weight, bitwidth=self.bitwidth, mode=mode)()
        if self.has_bias is True:
            self.buf_bias = SourceGen(binary_bias, bitwidth=self.bitwidth, mode=mode)()

        # define the kernel linear
        self.kernel = torch.nn.Linear(self.in_features, self.out_features, bias=self.has_bias)
        self.buf_wght_bs = BSGen(self.buf_wght, self.rng)
        self.rng_wght_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.weight, dtype=torch.long), requires_grad=False)
        if self.has_bias is True:
            self.buf_bias_bs = BSGen(self.buf_bias, self.rng)
            self.rng_bias_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel with inverse input, note that there is no bias required for this inverse kernel
        if self.mode == "bipolar":
            self.kernel_inv = torch.nn.Linear(self.in_features, self.out_features, bias=False)
            self.buf_wght_bs_inv = BSGen(self.buf_wght, self.rng)
            self.rng_wght_idx_inv = torch.nn.Parameter(torch.zeros_like(self.kernel_inv.weight, dtype=torch.long), requires_grad=False)

        self.parallel_cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        
        if self.scaled is True:
            self.rng_scale = RNG(round(math.log2(self.acc_bound.item())), (rng_idx+5)%1111, "Sobol")()
            self.rng_scale_idx = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        elif self.scaled is False:
            self.input_cnt = self.acc_bound.item()
            self.max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**depth-1), requires_grad=False)
            self.half_max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            self.cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            
    def UnaryKernel_accumulation(self, input):
        # generate weight and bias bits for current cycle
        self.kernel.weight.data = self.buf_wght_bs(self.rng_wght_idx).type(torch.float)
        self.rng_wght_idx.add_(input.type(torch.long))
        if self.has_bias is True:
            self.kernel.bias.data = self.buf_bias_bs(self.rng_bias_idx).type(torch.float)
            self.rng_bias_idx.add_(1)
            
        kernel_out = self.kernel(input.type(torch.float))

        if self.mode == "unipolar":
            return kernel_out
        
        if self.mode == "bipolar":
            self.kernel_inv.weight.data = 1 - self.buf_wght_bs_inv(self.rng_wght_idx_inv).type(torch.float)
            self.rng_wght_idx_inv.add_(1 - input.type(torch.long))
            kernel_out_inv = self.kernel_inv(1 - input.type(torch.float))
            return kernel_out + kernel_out_inv

    def forward(self, input):
        self.parallel_cnt.data = self.UnaryKernel_accumulation(input).type(torch.long)

        if self.scaled is True:
            output = torch.ge(self.parallel_cnt.data, self.rng_scale[self.rng_scale_idx%len(self.rng_scale)])
            self.rng_scale_idx.add_(1)
        else:
            if self.mode == "unipolar":
                output = torch.gt(self.parallel_cnt, 0)
            elif self.mode == "bipolar":
                self.parallel_cnt.mul_(2).sub_(self.input_cnt)
                self.cnt.data = self.cnt.add(self.parallel_cnt).clamp(0, self.max.item())
                output = torch.gt(self.cnt, self.half_max)

        return output.type(torch.int8)
    
    
class GainesLinear4(torch.nn.Module):
    """
    gMUL + gADD,
    this module is the same as GainesLinear1, except the rng is lfsr
    this module is the fully connected layer,
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) accumulation mode
    2) unary data mode
    3) binary data width
    4) binary weight
    5) binary bias
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 binary_weight=None, 
                 binary_bias=None, 
                 bitwidth=8, 
                 bias=True, 
                 mode="bipolar", 
                 scaled=True, 
                 depth=8, 
                 rng_idx=1):
        super(GainesLinear4, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        
        # upper bound for accumulation counter in non-scaled mode
        self.acc_bound = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        self.acc_bound.add_(in_features)
        if bias is True:
            self.acc_bound.add_(1)
            
        self.mode = mode
        self.scaled = scaled
        
        # accumulation offset
        self.offset = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
        if mode == "unipolar":
            pass
        elif mode == "bipolar":
            self.offset.add_((in_features-1)/2)
            if bias is True:
                self.offset.add_(1/2)
        else:
            raise ValueError("UnaryLinear mode is not implemented.")
        
        # bias indication for original linear layer
        self.has_bias = bias
        
        # data bit width
        self.bitwidth = bitwidth
        
        # random_sequence from sobol RNG
        self.rng = RNGMulti(self.bitwidth, in_features, "LFSR")()
        self.rng_bias = RNG(self.bitwidth, in_features+1, "LFSR")()
        
        # define the convolution weight and bias
        self.buf_wght = SourceGen(binary_weight, bitwidth=self.bitwidth, mode=mode)()
        if self.has_bias is True:
            self.buf_bias = SourceGen(binary_bias, bitwidth=self.bitwidth, mode=mode)()
        
        # define the kernel linear
        self.kernel = torch.nn.Linear(self.in_features, self.out_features, bias=self.has_bias)
        self.buf_wght_bs = BSGenMulti(self.buf_wght, self.rng, dim=0)
        self.rng_wght_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.weight, dtype=torch.long), requires_grad=False)
        if self.has_bias is True:
            self.buf_bias_bs = BSGen(self.buf_bias, self.rng_bias)
            self.rng_bias_idx = torch.nn.Parameter(torch.zeros_like(self.kernel.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel with inverse input, note that there is no bias required for this inverse kernel
        if self.mode == "bipolar":
            self.kernel_inv = torch.nn.Linear(self.in_features, self.out_features, bias=False)

        self.parallel_cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        
        if self.scaled is True:
            self.rng_scale = RNG(round(math.log2(self.acc_bound.item())), (rng_idx+5)%1111, "LFSR")()
            self.rng_scale_idx = torch.nn.Parameter(torch.zeros(1, dtype=torch.long), requires_grad=False)
        elif self.scaled is False:
            self.input_cnt = self.acc_bound.item()
            self.max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**depth-1), requires_grad=False)
            self.half_max = torch.nn.Parameter(torch.ones(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            self.cnt = torch.nn.Parameter(torch.zeros(1, dtype=torch.long).fill_(2**(depth-1)), requires_grad=False)
            
    def GainesKernel_accumulation(self, input):
        # generate weight and bias bits for current cycle
        self.kernel.weight.data = self.buf_wght_bs(self.rng_wght_idx).type(torch.float)
        self.rng_wght_idx.add_(1)
        if self.has_bias is True:
            self.kernel.bias.data = self.buf_bias_bs(self.rng_bias_idx).type(torch.float)
            self.rng_bias_idx.add_(1)
            
        kernel_out = self.kernel(input.type(torch.float))

        if self.mode == "unipolar":
            return kernel_out
        
        if self.mode == "bipolar":
            self.kernel_inv.weight.data = 1 - self.kernel.weight.data
            kernel_out_inv = self.kernel_inv(1 - input.type(torch.float))
            return kernel_out + kernel_out_inv

    def forward(self, input):
        self.parallel_cnt.data = self.GainesKernel_accumulation(input).type(torch.long)

        if self.scaled is True:
            output = torch.ge(self.parallel_cnt.data, self.rng_scale[self.rng_scale_idx%len(self.rng_scale)])
            self.rng_scale_idx.add_(1)
        else:
            if self.mode == "unipolar":
                output = torch.gt(self.parallel_cnt, 0)
            elif self.mode == "bipolar":
                self.parallel_cnt.mul_(2).sub_(self.input_cnt)
                self.cnt.data = self.cnt.add(self.parallel_cnt).clamp(0, self.max.item())
                output = torch.gt(self.cnt, self.half_max)

        return output.type(torch.int8)