import torch
import math
import copy
from UnarySim.stream import RNG, BinGen, BSGen
from UnarySim.kernel import FSUAdd
from torch.cuda.amp import autocast

class FSULinear(torch.nn.Module):
    """
    This module is the fully connected layer, and its API is similar to the Linear class (input/output feature count, bias flag), except:
    1) weight_ext: external binary weight
    2) bias_ext: external binary bias
    3) width: binary data width
    4) mode: unary data mode
    5) scale: accumulation scale
    6) depth: accumulator depth
    7) rng: weight rng type
    8) dimr: weight rng dimension

    The allowed coding for input, weight and bias with guaranteed accuracy can have the following three options.s
    (input, weight, bias):
    1) rate, rate, rate
    2) rate, temporal, rate
    3) temporal, rate, rate
    However, this module itself does not force the input coding. Thus, above coding constraints should be done by users.
    """
    def __init__(
        self, 
        in_features, 
        out_features, 
        bias=True, 
        weight_ext=None, 
        bias_ext=None, 
        hwcfg={
            "width" : 8,
            "mode" : "bipolar",
            "scale" : None,
            "depth" : 12,
            "rng" : "Sobol",
            "dimr" : 1
        },
        swcfg={
            "btype" : torch.float, 
            "rtype" : torch.float, 
            "stype" : torch.float
        }):
        super(FSULinear, self).__init__()
        self.hwcfg = {}
        self.hwcfg["width"] = hwcfg["width"]
        self.hwcfg["mode"] = hwcfg["mode"].lower()
        self.hwcfg["scale"] = hwcfg["scale"]
        self.hwcfg["depth"] = hwcfg["depth"]
        self.hwcfg["rng"] = hwcfg["rng"]
        self.hwcfg["dimr"] = hwcfg["dimr"]

        self.swcfg = {}
        self.swcfg["btype"] = swcfg["btype"]
        self.swcfg["rtype"] = swcfg["rtype"]
        self.swcfg["stype"] = swcfg["stype"]

        self.PC = FSULinearPC(
            in_features, 
            out_features, 
            bias=bias, 
            weight_ext=weight_ext, 
            bias_ext=bias_ext, 
            hwcfg=self.hwcfg,
            swcfg=self.swcfg)

        self.scale = hwcfg["scale"]
        if self.scale is None:
            scale_add = in_features + bias
        else:
            scale_add = self.scale
        hwcfg_acc = copy.deepcopy(self.hwcfg)
        hwcfg_acc["scale"] = scale_add
        hwcfg_acc["entry"] = in_features + bias
        hwcfg_acc["dima"] = 1
        self.ACC = FSUAdd(
            hwcfg_acc,
            self.swcfg)

    @autocast()
    def forward(self, input, scale=None, entry=None):
        pc = self.PC(input)
        output = self.ACC(pc.unsqueeze(0), scale, entry)
        return output


class FSULinearPC(torch.nn.Linear):
    """
    This module is the parallel counter result of FSULinear before generating the bitstreams.
    The allowed coding for input, weight and bias with guaranteed accuracy can have the following three options.s
    (input, weight, bias):
    1) rate, rate, rate
    2) rate, temporal, rate
    3) temporal, rate, rate
    However, this module itself does not force the input coding. Thus, above coding constraints should be done by users.
    """
    def __init__(
        self, 
        in_features, 
        out_features, 
        bias=True, 
        weight_ext=None, 
        bias_ext=None, 
        hwcfg={
            "width" : 8,
            "mode" : "bipolar",
            "rng" : "Sobol",
            "dimr" : 1
        },
        swcfg={
            "btype" : torch.float, 
            "rtype" : torch.float, 
            "stype" : torch.float
        }):
        super(FSULinearPC, self).__init__(in_features, out_features, bias=bias)
        self.hwcfg = {}
        self.hwcfg["width"] = hwcfg["width"]
        self.hwcfg["mode"] = hwcfg["mode"].lower()
        self.hwcfg["rng"] = hwcfg["rng"]
        self.hwcfg["dimr"] = hwcfg["dimr"]

        self.swcfg = {}
        self.swcfg["btype"] = swcfg["btype"]
        self.swcfg["rtype"] = swcfg["rtype"]
        self.swcfg["stype"] = swcfg["stype"]
        
        self.width = hwcfg["width"]
        self.mode = hwcfg["mode"].lower()
        assert self.mode in ["unipolar", "bipolar"], \
            "Error: the hw config 'mode' in " + self + " class requires one of ['unipolar', 'bipolar']."

        self.btype = swcfg["btype"]
        self.rtype = swcfg["rtype"]
        self.stype = swcfg["stype"]

        # bias indication for original linear layer
        self.has_bias = bias
        
        # RNG for weight
        hwcfg_wrng = {
            "width" : hwcfg["width"],
            "rng" : hwcfg["rng"],
            "dimr" : hwcfg["dimr"]
        }
        self.wrng = RNG(hwcfg_wrng, swcfg)()
        if hwcfg["rng"].lower() == "race" or "tc":
            self.wtc = True
        else:
            self.wtc = False
        
        # define the linear weight and bias
        if weight_ext is not None:
            assert (weight_ext.size()[0], weight_ext.size()[1]) == (out_features, in_features), \
                "Error: the hw config 'out_features, in_features' in " + self + " class unmatches the binary weight shape."
            self.weight.data = BinGen(weight_ext, self.hwcfg, self.swcfg)()
        
        if bias and (bias_ext is not None):
            assert bias_ext.size()[0] == out_features, \
                "Error: the hw config 'out_features' in " + self + " class unmatches the binary bias shape."
            self.bias.data = BinGen(bias_ext, self.hwcfg, self.swcfg)()
            # RNG for bias, should always apply rate coding
            hwcfg_brng = {
                "width" : hwcfg["width"],
                "rng" : "sobol",
                "dimr" : hwcfg["dimr"]
            }
            self.brng = RNG(hwcfg_brng, swcfg)()

        # define the kernel linear for input bit 1
        self.wbsg_i1 = BSGen(self.weight, self.wrng, hwcfg, swcfg)
        self.wrdx_i1 = torch.nn.Parameter(torch.zeros_like(self.weight, dtype=torch.long), requires_grad=False).unsqueeze(0)
        if self.has_bias is True:
            self.bbsg = BSGen(self.bias, self.brng, hwcfg, swcfg)
            self.brdx = torch.nn.Parameter(torch.zeros_like(self.bias, dtype=torch.long), requires_grad=False)
        
        # if bipolar, define a kernel for input bit 0, note that there is no bias required for this kernel
        if (self.mode == "bipolar") and (self.wtc is False):
            self.wbsg_i0 = BSGen(self.weight, self.wrng, hwcfg, swcfg)
            self.wrdx_i0 = torch.nn.Parameter(torch.zeros_like(self.weight, dtype=torch.long), requires_grad=False).unsqueeze(0)

    def FSULinear_PC_wrc(self, input):
        # this function is for weight with rate coding
        # first dim should always be batch
        batch = input.size()[0]

        # generate weight and bias bits for current cycle
        wbit_i1 = self.wbsg_i1(self.wrdx_i1).type(torch.float)
        if wbit_i1.size()[0] != batch:
            wbit_i1 = torch.cat(batch*[wbit_i1], 0)
            self.wrdx_i1 = torch.cat(batch*[self.wrdx_i1], 0)
        torch.add(self.wrdx_i1, input.unsqueeze(1).type(torch.long), out=self.wrdx_i1)
        
        out_i1 = torch.empty(0, device=input.device)
        torch.matmul(input.unsqueeze(1).type(torch.float), wbit_i1.transpose(1, 2), out=out_i1)
        out_i1.squeeze_(1)
        
        if self.has_bias is True:
            bbit = self.bbsg(self.brdx).type(torch.float)
            self.brdx.add_(1)
            out_i1 += bbit.unsqueeze(0).expand_as(out_i1)

        if self.mode == "unipolar":
            return out_i1
        
        if self.mode == "bipolar":
            # generate weight and bias bits for current cycle
            wbit_i0 = 1 - self.wbsg_i0(self.wrdx_i0).type(torch.float)
            if wbit_i0.size()[0] != batch:
                wbit_i0 = torch.cat(batch*[wbit_i0], 0)
                self.wrdx_i0 = torch.cat(batch*[self.wrdx_i0], 0)
            torch.add(self.wrdx_i0, 1 - input.unsqueeze(1).type(torch.long), out=self.wrdx_i0)
            
            out_i0 = torch.empty(0, device=input.device)
            torch.matmul(1 - input.unsqueeze(1).type(torch.float), wbit_i0.transpose(1, 2), out=out_i0)
            out_i0.squeeze_(1)

            return out_i1 + out_i0
    
    def FSULinear_PC_wtc(self, input):
        # this function is for weight with temporal coding
        # first dim should always be batch
        batch = input.size()[0]

        # generate weight and bias bits for current cycle
        wbit_i1 = self.wbsg_i1(self.wrdx_i1).type(torch.float)
        if wbit_i1.size()[0] != batch:
            wbit_i1 = torch.cat(batch*[wbit_i1], 0)
            self.wrdx_i1 = torch.cat(batch*[self.wrdx_i1], 0)
        torch.add(self.wrdx_i1, torch.ones_like(input).unsqueeze(1).type(torch.long), out=self.wrdx_i1)
        
        out_i1 = torch.empty(0, device=input.device)
        torch.matmul(input.unsqueeze(1).type(torch.float), wbit_i1.transpose(1, 2), out=out_i1)
        out_i1.squeeze_(1)
        
        if self.has_bias is True:
            bbit = self.bbsg(self.brdx).type(torch.float)
            self.brdx.add_(1)
            out_i1 += bbit.unsqueeze(0).expand_as(out_i1)

        if self.mode == "unipolar":
            return out_i1
        
        if self.mode == "bipolar":
            # generate weight and bias bits for current cycle
            wbit_i0 = 1 - wbit_i1
            out_i0 = torch.empty(0, device=input.device)
            torch.matmul(1 - input.unsqueeze(1).type(torch.float), wbit_i0.transpose(1, 2), out=out_i0)
            out_i0.squeeze_(1)

            return out_i1 + out_i0

    @autocast()
    def forward(self, input):
        if self.wtc:
            return self.FSULinear_PC_wtc(input).type(self.stype)
        else:
            return self.FSULinear_PC_wrc(input).type(self.stype)
        

# the HUBLinear and HUBLinearFunction are parallel implementations
class HUBLinear(torch.nn.Linear):
    """
    this module is the fully connected layer, with binary input and binary output
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) binary data scale factor
    2) binary weight
    3) binary bias
    4) mac cycle
    This cycle is the mac cycle using unipolar umul, i.e., half the bipolar umul. 
    As such, cycle = 2 ^ (bitwidth - 1).
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 bias=True, 
                 weight_ext=None, 
                 bias_ext=None, 
                 rng="Sobol", 
                 cycle=128,
                 rounding="round"):
        super(HUBLinear, self).__init__(in_features, out_features, bias)
        
        # weight and bias
        if weight_ext is not None:
            self.weight.data = weight_ext
        
        if bias and (bias_ext is not None):
            self.bias.data = bias_ext
        
        # mac computing cycle
        self.cycle = cycle
        
        # bitwidth of rng
        self.bitwidth = (self.cycle - 1).bit_length()
        
        # random_sequence from sobol RNG
        self.irng = RNG(self.bitwidth, 1, rng)()
        self.wrng = RNG(self.bitwidth, 1, "Sobol")()
        
        # generate the value map for mul using current rng
        # dim 0 is input index
        # the tensor input value is the actual value produced by the rng
        self.input_map = torch.nn.Parameter(torch.empty(cycle), requires_grad=False)
        input_val_cycle = torch.empty(0)
        torch.cat(cycle*[torch.arange(cycle, dtype=torch.float).unsqueeze(1)], 1, out=input_val_cycle)
        input_bit_cycle = torch.empty(0)
        torch.gt(input_val_cycle, self.irng.unsqueeze(0), out=input_bit_cycle)
        self.input_map.data = torch.sum(input_bit_cycle, 1).squeeze_().type(torch.long)

        # dim 0 is input index, dim 1 is weight index
        # the tensor value is the actual weight value produced by the rng, under a specific input and weight
        self.wght_map = torch.nn.Parameter(torch.empty(cycle, cycle), requires_grad=False)
        wght_bit_cycle = torch.empty(0)
        torch.gt(input_val_cycle, self.wrng.unsqueeze(0), out=wght_bit_cycle)
        for c in range(cycle):
            self.wght_map.data[c] = torch.sum(wght_bit_cycle[:, 0:self.input_map.data[c]], 1).squeeze_()
        
        # rounding mode
        self.rounding = rounding
        
        self.rshift_input = None
        self.rshift_wght = None
        self.rshift_output = None
        
    @autocast()
    def forward(self, input):
        # See the autograd section for explanation of what happens here.
        with torch.no_grad():
            input_max_int = input.abs().max().log2()
            wght_max_int = self.weight.abs().max().log2()
            if self.rounding == "round":
                input_max_int = input_max_int.round()
                wght_max_int = wght_max_int.round()
            elif self.rounding == "floor":
                input_max_int = input_max_int.floor()
                wght_max_int = wght_max_int.floor()
            elif self.rounding == "ceil":
                input_max_int = input_max_int.ceil()
                wght_max_int = wght_max_int.ceil()

            self.rshift_input = input_max_int - self.bitwidth
            self.rshift_wght = wght_max_int - self.bitwidth
            self.rshift_output = self.bitwidth - input_max_int - wght_max_int
        
        return HUBLinearFunction.apply(input, self.weight, self.bias, self.rshift_input, self.rshift_wght, self.rshift_output, self.cycle, self.wght_map)

    
# Inherit from Function
class HUBLinearFunction(torch.autograd.Function):

    # Note that both forward and backward are @staticmethods
    @staticmethod
    # bias is an optional argument
    def forward(ctx, input, weight, bias=None, 
                rshift_input=3, 
                rshift_wght=3, 
                rshift_output=3, 
                cycle=128, 
                wght_map=None):
        ctx.save_for_backward(input, weight, bias)

        # first dim should always be batch
        batch = input.size()[0]
        
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # input preparation
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # scale input to range 0~2^bitwidth-1
        buf_input = torch.empty(0, dtype=torch.long, device=input.device)
        torch.abs((input >> rshift_input).unsqueeze_(1).type(torch.long), out=buf_input)
        torch.clamp(buf_input, 0, cycle-1, out=buf_input)
        
        # actual input: its sign
        act_input = torch.empty(0, device=input.device)
        torch.sign(input, out=act_input)
        act_input.unsqueeze_(1)
        
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # weight preparation
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # scale weight with batch to range 0~2^bitwidth-1
        buf_wght_no_batch = torch.empty(0, dtype=torch.long, device=weight.device)
        torch.abs((weight >> rshift_wght).unsqueeze_(0).type(torch.long), out=buf_wght_no_batch)
        torch.clamp(buf_wght_no_batch, 0, cycle-1, out=buf_wght_no_batch)
        buf_wght = torch.empty(0, dtype=torch.long, device=weight.device)
        torch.cat(batch*[buf_wght_no_batch], 0, out=buf_wght)

        # get actual weight for calculation
        sign_wght_no_batch = torch.empty(0, device=weight.device)
        torch.sign(weight, out=sign_wght_no_batch)
        sign_wght_no_batch.unsqueeze_(0)
        act_wght = torch.empty(0, device=weight.device)
        torch.cat(batch*[sign_wght_no_batch], 0, out=act_wght)
        torch.mul(wght_map[buf_input, buf_wght], act_wght, out=act_wght)
        
        output = torch.empty(0, device=weight.device)
        torch.matmul(act_input, act_wght.transpose(1, 2), out=output)
        
        output = (output >> rshift_output).squeeze_(1)
        
        if bias is not None:
            output += bias.unsqueeze(0).expand_as(output)
        return output

    # This function has only a single output, so it gets only one gradient
    @staticmethod
    def backward(ctx, grad_output):
        # This is a pattern that is very convenient - at the top of backward
        # unpack saved_tensors and initialize all gradients w.r.t. inputs to
        # None. Thanks to the fact that additional trailing Nones are
        # ignored, the return statement is simple even when the function has
        # optional inputs.
        input, weight, bias = ctx.saved_tensors
        grad_input = grad_weight = grad_bias = None

        # These needs_input_grad checks are optional and there only to
        # improve efficiency. If you want to make your code simpler, you can
        # skip them. Returning gradients for inputs that don't require it is
        # not an error.
        if ctx.needs_input_grad[0]:
            grad_input = grad_output.matmul(weight)
        if ctx.needs_input_grad[1]:
            grad_weight = grad_output.t().matmul(input)
        if bias is not None and ctx.needs_input_grad[2]:
            grad_bias = grad_output.sum(0)

        return grad_input, grad_weight, grad_bias, None, None, None, None, None

    
class FXPLinear(torch.nn.Linear):
    """
    this module is the fully connected layer, with binary input and binary output
    its API is similar to the parent class (input/output feature count, bias flag), except:
    1) binary data scale factor
    2) binary weight
    3) binary bias
    4) mac cycle
    """
    def __init__(self, 
                 in_features, 
                 out_features, 
                 bias=True, 
                 weight_ext=None, 
                 bias_ext=None, 
                 bitwidth=8, 
                 keep_res="input", # keep the resolution of input/output
                 more_res="input", # assign more resolution to input/weight
                 rounding="round"):
        super(FXPLinear, self).__init__(in_features, out_features, bias)

        # weight and bias
        if weight_ext is not None:
            self.weight.data = weight_ext
        
        if bias and (bias_ext is not None):
            self.bias.data = bias_ext
        
        # bitwidth of abs
        if isinstance(bitwidth, tuple):
            self.bw_input, self.bw_wght = (bitwidth[0]-1, bitwidth[1]-1)
        else:
            if keep_res == "input":
                self.bw_input, self.bw_wght = (bitwidth-1, bitwidth-1)
            elif keep_res == "output":
                if bitwidth % 2 == 0:
                    self.bw_input, self.bw_wght = (int(bitwidth/2 - 1), int(bitwidth/2 - 1))
                else:
                    if more_res == "input":
                        self.bw_input, self.bw_wght = (int((bitwidth+1)/2 - 1), int((bitwidth-1)/2 - 1))
                    elif more_res == "weight":
                        self.bw_input, self.bw_wght = (int((bitwidth-1)/2 - 1), int((bitwidth+1)/2 - 1))
                    else:
                        raise ValueError("more_res should be either 'input' or 'weight' when bitwidth is not a tuple and keep_res is 'output'.")
            else:
                raise ValueError("keep_res should be either 'input' or 'output' when bitwidth is not a tuple.")
        
        # max abs value
        self.max_abs_input = 2**self.bw_input
        self.max_abs_wght = 2**self.bw_wght
        
        # rounding mode
        self.rounding = rounding
        
        self.rshift_input = None
        self.rshift_wght = None
        self.rshift_output = None
    
    @autocast()
    def forward(self, input):
        # See the autograd section for explanation of what happens here.
        with torch.no_grad():
            if self.rshift_input is None:
                input_max_int = input.abs().max().log2()
                if self.rounding == "round":
                    input_max_int = input_max_int.round()
                elif self.rounding == "floor":
                    input_max_int = input_max_int.floor()
                elif self.rounding == "ceil":
                    input_max_int = input_max_int.ceil()
                self.rshift_input = input_max_int - self.bw_input
            
            if self.rshift_wght is None:
                wght_max_int = self.weight.abs().max().log2()
                if self.rounding == "round":
                    wght_max_int = wght_max_int.round()
                elif self.rounding == "floor":
                    wght_max_int = wght_max_int.floor()
                elif self.rounding == "ceil":
                    wght_max_int = wght_max_int.ceil()
                self.rshift_wght = wght_max_int - self.bw_wght
                
            if self.rshift_output is None:
                self.rshift_output = 0 - self.rshift_input - self.rshift_wght
        
        return FXPLinearFunction.apply(input, self.weight, self.bias, self.rshift_input, self.rshift_wght, self.rshift_output, self.max_abs_input, self.max_abs_wght)

    
# Inherit from Function
class FXPLinearFunction(torch.autograd.Function):

    # Note that both forward and backward are @staticmethods
    @staticmethod
    # bias is an optional argument
    def forward(ctx, input, weight, bias=None, 
                rshift_input=3, 
                rshift_wght=3, 
                rshift_output=3, 
                max_abs_input=128, 
                max_abs_wght=128):
        ctx.save_for_backward(input, weight, bias)
        
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # input preparation
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # round input to (bot, top)
        bot_input = 0 - max_abs_input
        top_input = max_abs_input - 1
        input_round = torch.empty(0, device=input.device)
        torch.round(input >> rshift_input, out=input_round)
        torch.clamp(input_round.unsqueeze_(1), bot_input, top_input, out=input_round)
        
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # weight preparation
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
        # round input to (bot, top)
        bot_wght = 0 - max_abs_wght
        top_wght = max_abs_wght - 1
        wght_round = torch.empty(0, device=input.device)
        torch.round(weight >> rshift_wght, out=wght_round)
        torch.clamp(wght_round.unsqueeze_(0), bot_wght, top_wght, out=wght_round)
        
        output = torch.empty(0, device=weight.device)
        torch.matmul(input_round, wght_round.transpose(1, 2), out=output)
        output = (output >> rshift_output).squeeze_(1)
        
        if bias is not None:
            output += bias.unsqueeze(0).expand_as(output)
        return output

    # This function has only a single output, so it gets only one gradient
    @staticmethod
    def backward(ctx, grad_output):
        # This is a pattern that is very convenient - at the top of backward
        # unpack saved_tensors and initialize all gradients w.r.t. inputs to
        # None. Thanks to the fact that additional trailing Nones are
        # ignored, the return statement is simple even when the function has
        # optional inputs.
        input, weight, bias = ctx.saved_tensors
        grad_input = grad_weight = grad_bias = None

        # These needs_input_grad checks are optional and there only to
        # improve efficiency. If you want to make your code simpler, you can
        # skip them. Returning gradients for inputs that don't require it is
        # not an error.
        if ctx.needs_input_grad[0]:
            grad_input = grad_output.matmul(weight)
        if ctx.needs_input_grad[1]:
            grad_weight = grad_output.t().matmul(input)
        if bias is not None and ctx.needs_input_grad[2]:
            grad_bias = grad_output.sum(0)

        return grad_input, grad_weight, grad_bias, None, None, None, None, None